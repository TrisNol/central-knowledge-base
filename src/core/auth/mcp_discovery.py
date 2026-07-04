from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlparse

import httpx

from src.core.auth.models import OAuthProvider, ProviderDiscoveryMetadata


class OAuthDiscoveryError(RuntimeError):
    pass


@dataclass
class _CacheEntry:
    value: ProviderDiscoveryMetadata
    expires_at: float


class MCPOAuthDiscoveryService:
    """Discovers OAuth metadata starting from an MCP endpoint challenge."""

    def __init__(
        self,
        provider_endpoints: dict[OAuthProvider, str],
        ttl_seconds: int = 300,
        fallback_authorization_servers: dict[OAuthProvider, str] | None = None,
    ):
        self._provider_endpoints = provider_endpoints
        self._ttl_seconds = ttl_seconds
        self._fallback_authorization_servers = fallback_authorization_servers or {}
        self._cache: dict[OAuthProvider, _CacheEntry] = {}
        self._lock = Lock()

    async def discover(self, provider: OAuthProvider) -> ProviderDiscoveryMetadata:
        cached = self._get_cached(provider)
        if cached:
            return cached

        mcp_url = self._provider_endpoints[provider]
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            challenge = await client.get(mcp_url)
            if challenge.status_code != 401:
                raise OAuthDiscoveryError(
                    f"Expected 401 challenge from MCP endpoint, got {challenge.status_code}."
                )

            resource_metadata = await self._discover_resource_metadata(
                client=client,
                provider=provider,
                mcp_url=mcp_url,
                www_authenticate=challenge.headers.get("WWW-Authenticate"),
            )
            resource_metadata_url = resource_metadata.get("_resource_metadata_url", "")

            authorization_servers = resource_metadata.get("authorization_servers")
            if not isinstance(authorization_servers, list) or not authorization_servers:
                raise OAuthDiscoveryError(
                    "Protected resource metadata is missing authorization_servers."
                )

            authorization_server = str(authorization_servers[0]).rstrip("/")
            self._validate_https(authorization_server)

            authorization_metadata = await self._fetch_authorization_server_metadata(
                client,
                authorization_server,
            )

            discovered = ProviderDiscoveryMetadata(
                provider=provider,
                mcp_url=mcp_url,
                resource=str(resource_metadata.get("resource") or mcp_url),
                resource_metadata_url=resource_metadata_url,
                resource_metadata=resource_metadata,
                authorization_server=authorization_server,
                authorization_server_metadata=authorization_metadata,
            )
            self._set_cached(provider, discovered)
            return discovered

    async def _discover_resource_metadata(
        self,
        client: httpx.AsyncClient,
        provider: OAuthProvider,
        mcp_url: str,
        www_authenticate: str | None,
    ) -> dict[str, Any]:
        resource_metadata_url = self._extract_resource_metadata_url(www_authenticate)
        candidate_urls = self._resource_metadata_candidates(
            mcp_url, resource_metadata_url
        )

        for url in candidate_urls:
            if not url:
                continue
            try:
                self._validate_https(url)
                self._validate_same_host(mcp_url, url)
            except OAuthDiscoveryError:
                continue

            response = await client.get(url)
            if response.status_code != 200:
                continue

            payload = response.json()
            authorization_servers = payload.get("authorization_servers")
            if isinstance(authorization_servers, list) and authorization_servers:
                payload["_resource_metadata_url"] = url
                return payload

        # Some MCP servers (including Atlassian) may not expose protected-resource metadata,
        # but still expose OAuth authorization server metadata at the MCP origin.
        origin_authorization_server = (
            await self._discover_authorization_server_from_mcp_origin(
                client,
                mcp_url,
            )
        )
        if origin_authorization_server:
            return {
                "authorization_servers": [origin_authorization_server],
                "resource": mcp_url,
                "_resource_metadata_url": "",
            }

        fallback_auth_server = self._fallback_authorization_servers.get(provider)
        if fallback_auth_server:
            self._validate_https(fallback_auth_server)
            return {
                "authorization_servers": [fallback_auth_server],
                "resource": mcp_url,
                "_resource_metadata_url": "",
            }

        raise OAuthDiscoveryError(
            "Unable to resolve protected resource metadata from challenge."
        )

    @staticmethod
    async def _discover_authorization_server_from_mcp_origin(
        client: httpx.AsyncClient,
        mcp_url: str,
    ) -> str | None:
        parsed = urlparse(mcp_url)
        if not parsed.scheme or not parsed.netloc:
            return None

        origin = f"{parsed.scheme}://{parsed.netloc}"
        metadata_url = f"{origin}/.well-known/oauth-authorization-server"
        try:
            response = await client.get(metadata_url)
            if response.status_code != 200:
                return None
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        issuer = payload.get("issuer")
        if isinstance(issuer, str) and issuer:
            return issuer.rstrip("/")
        return None

    @staticmethod
    def _resource_metadata_candidates(
        mcp_url: str,
        challenge_resource_metadata_url: str | None,
    ) -> list[str]:
        parsed = urlparse(mcp_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.strip("/")

        candidates: list[str] = []
        if challenge_resource_metadata_url:
            candidates.append(challenge_resource_metadata_url)

        if path:
            candidates.append(f"{origin}/.well-known/oauth-protected-resource/{path}")
            candidates.append(f"{origin}/.well-known/oauth-protected-resource/{path}/")

        candidates.append(f"{origin}/.well-known/oauth-protected-resource")
        candidates.append(f"{mcp_url.rstrip('/')}/.well-known/oauth-protected-resource")

        # Preserve order while removing duplicates.
        deduped: list[str] = []
        seen: set[str] = set()
        for url in candidates:
            if url not in seen:
                seen.add(url)
                deduped.append(url)
        return deduped

    async def _fetch_authorization_server_metadata(
        self,
        client: httpx.AsyncClient,
        issuer: str,
    ) -> dict[str, Any]:
        candidates = self._authorization_metadata_candidates(issuer)

        for url in candidates:
            response = await client.get(url)
            if response.status_code == 200:
                metadata = response.json()
                if (
                    "authorization_endpoint" in metadata
                    and "token_endpoint" in metadata
                ):
                    return metadata

        raise OAuthDiscoveryError("Unable to resolve authorization server metadata.")

    @staticmethod
    def _authorization_metadata_candidates(issuer: str) -> list[str]:
        """Build RFC 8414/OIDC well-known URLs, including issuers that contain a path."""
        issuer = issuer.rstrip("/")
        parsed = urlparse(issuer)
        if not parsed.scheme or not parsed.netloc:
            raise OAuthDiscoveryError("Invalid authorization server issuer URL.")

        path = parsed.path.strip("/")
        base = f"{parsed.scheme}://{parsed.netloc}"
        with_path = f"/{path}" if path else ""

        # RFC 8414 (issuer with path):
        # https://host/.well-known/oauth-authorization-server/{issuer_path}
        # OIDC analogue:
        # https://host/.well-known/openid-configuration/{issuer_path}
        candidates = [
            f"{base}/.well-known/oauth-authorization-server{with_path}",
            f"{base}/.well-known/openid-configuration{with_path}",
            # Non-standard but common variant where well-known is under issuer path.
            f"{issuer}/.well-known/oauth-authorization-server",
            f"{issuer}/.well-known/openid-configuration",
        ]

        return candidates

    @staticmethod
    def _extract_resource_metadata_url(www_authenticate: str | None) -> str | None:
        if not www_authenticate:
            return None

        lower_value = www_authenticate.lower()
        marker = 'resource_metadata="'
        marker_index = lower_value.find(marker)
        if marker_index == -1:
            return None

        value_start = marker_index + len(marker)
        value_end = www_authenticate.find('"', value_start)
        if value_end == -1:
            return None

        value = www_authenticate[value_start:value_end]
        if not value:
            return None
        return value

    @staticmethod
    def _validate_https(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme == "https":
            return
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return
        raise OAuthDiscoveryError("OAuth discovery endpoints must be HTTPS.")

    @staticmethod
    def _validate_same_host(mcp_url: str, metadata_url: str) -> None:
        mcp_host = urlparse(mcp_url).hostname
        metadata_host = urlparse(metadata_url).hostname
        if not mcp_host or not metadata_host:
            raise OAuthDiscoveryError("Could not validate resource metadata host.")

        if mcp_host != metadata_host and metadata_host not in {
            "localhost",
            "127.0.0.1",
        }:
            raise OAuthDiscoveryError(
                "resource_metadata host does not match the MCP endpoint host."
            )

    def _get_cached(self, provider: OAuthProvider) -> ProviderDiscoveryMetadata | None:
        with self._lock:
            entry = self._cache.get(provider)
            if not entry:
                return None
            if entry.expires_at < monotonic():
                self._cache.pop(provider, None)
                return None
            return entry.value

    def _set_cached(
        self, provider: OAuthProvider, value: ProviderDiscoveryMetadata
    ) -> None:
        with self._lock:
            self._cache[provider] = _CacheEntry(
                value=value,
                expires_at=monotonic() + self._ttl_seconds,
            )
