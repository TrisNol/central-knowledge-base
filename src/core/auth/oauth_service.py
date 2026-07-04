from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from src.config import (
    build_fallback_access_tokens_from_env,
    build_preconfigured_clients_from_env,
)
from src.core.auth.mcp_discovery import MCPOAuthDiscoveryService
from src.core.auth.models import (
    OAuthClientRegistration,
    OAuthProvider,
    OAuthTokenState,
    PendingOAuthState,
    ProviderConnectionStatus,
)
from src.core.auth.session_store import OAuthSessionStore


class OAuthFlowError(RuntimeError):
    pass


def _b64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def redact_secret(value: str | None) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "<redacted>"
    return f"{value[:4]}...{value[-4:]}"


class OAuthService:
    def __init__(
        self,
        session_store: OAuthSessionStore,
        discovery_service: MCPOAuthDiscoveryService,
        frontend_base_url: str,
        backend_base_url: str,
        provider_scopes: dict[OAuthProvider, str],
        fallback_access_tokens: dict[OAuthProvider, str],
        preconfigured_clients: dict[OAuthProvider, OAuthClientRegistration]
        | None = None,
    ):
        self._store = session_store
        self._discovery = discovery_service
        self._frontend_base_url = frontend_base_url.rstrip("/")
        self._backend_base_url = backend_base_url.rstrip("/")
        self._provider_scopes = provider_scopes
        self._fallback_access_tokens = fallback_access_tokens
        self._preconfigured_clients = preconfigured_clients or {}

    def has_fallback_access_token(self, provider: OAuthProvider) -> bool:
        return bool(self._fallback_access_tokens.get(provider))

    def get_fallback_access_tokens(self) -> dict[OAuthProvider, str]:
        """Get all fallback access tokens."""
        return dict(self._fallback_access_tokens)

    def has_session_access_token(
        self, session_id: str, provider: OAuthProvider
    ) -> bool:
        return self._store.get_token(session_id, provider) is not None

    async def start_connect(
        self, session_id: str, provider: OAuthProvider, redirect_uri: str
    ) -> str:
        metadata = await self._discovery.discover(provider)

        client = await self._resolve_client_registration(
            session_id=session_id,
            provider=provider,
            metadata=metadata.authorization_server_metadata,
        )

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        pending = PendingOAuthState(
            provider=provider,
            state=state,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            nonce=secrets.token_urlsafe(24),
        )
        self._store.save_pending(session_id, pending)

        auth_endpoint = metadata.authorization_server_metadata.get(
            "authorization_endpoint"
        )
        if not auth_endpoint:
            raise OAuthFlowError(
                "Authorization server metadata missing authorization_endpoint."
            )

        query_params = {
            "response_type": "code",
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "scope": self._provider_scopes.get(provider, ""),
            "state": state,
            "code_challenge": _b64url_sha256(code_verifier),
            "code_challenge_method": "S256",
        }

        # RFC 8707 resource indicator improves audience targeting for MCP resource servers.
        if provider == OAuthProvider.ATLASSIAN:
            # Atlassian MCP authorization endpoint requires explicit consent.
            query_params["prompt"] = "consent"
        elif metadata.resource:
            query_params["resource"] = metadata.resource

        if "openid" in query_params["scope"].split():
            query_params["nonce"] = pending.nonce

        return f"{auth_endpoint}?{urlencode(query_params)}"

    async def handle_callback(
        self,
        session_id: str,
        provider: OAuthProvider,
        state: str,
        code: str,
    ) -> None:
        pending = self._store.pop_pending(session_id, state)
        if not pending:
            raise OAuthFlowError("Invalid or expired OAuth state.")
        if pending.provider != provider:
            raise OAuthFlowError("OAuth provider mismatch for callback state.")

        metadata = await self._discovery.discover(provider)
        token_endpoint = metadata.authorization_server_metadata.get("token_endpoint")
        if not token_endpoint:
            raise OAuthFlowError(
                "Authorization server metadata missing token_endpoint."
            )

        client = await self._resolve_client_registration(
            session_id=session_id,
            provider=provider,
            metadata=metadata.authorization_server_metadata,
        )

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending.redirect_uri,
            "client_id": client.client_id,
            "code_verifier": pending.code_verifier,
        }

        if provider != OAuthProvider.ATLASSIAN and metadata.resource:
            data["resource"] = metadata.resource

        headers = {"Accept": "application/json"}
        if (
            client.client_secret
            and client.token_endpoint_auth_method == "client_secret_basic"
        ):
            basic_value = base64.b64encode(
                f"{client.client_id}:{client.client_secret}".encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = f"Basic {basic_value}"
        elif client.client_secret:
            data["client_secret"] = client.client_secret

        async with httpx.AsyncClient(timeout=20.0) as client_http:
            response = await client_http.post(
                token_endpoint,
                headers=headers,
                data=data,
            )
            if response.status_code >= 400:
                response_detail = self._safe_response_detail(response)
                raise OAuthFlowError(
                    f"Token exchange failed with status {response.status_code}. {response_detail}"
                )
            token_payload = response.json()

        access_token = token_payload.get("access_token")
        if not access_token:
            raise OAuthFlowError("Token exchange response missing access_token.")

        expires_in = token_payload.get("expires_in")
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            if expires_in is not None
            else None
        )

        token_state = OAuthTokenState(
            provider=provider,
            access_token=access_token,
            refresh_token=token_payload.get("refresh_token"),
            token_type=token_payload.get("token_type", "Bearer"),
            scope=token_payload.get("scope"),
            expires_at=expires_at,
            metadata={
                "resource_server": metadata.mcp_url,
                "authorization_server": metadata.authorization_server,
            },
        )
        self._store.save_token(session_id, token_state)

    def disconnect(self, session_id: str, provider: OAuthProvider) -> None:
        self._store.remove_token(session_id, provider)

    def statuses(self, session_id: str) -> list[ProviderConnectionStatus]:
        statuses = self._store.statuses(session_id)
        for status in statuses:
            if status.connected:
                status.connection_type = "oauth"
            elif status.provider in self._fallback_access_tokens:
                status.connected = True
                status.connection_type = "fallback"
            else:
                status.connection_type = "none"
        return statuses

    async def get_valid_access_token(
        self, session_id: str, provider: OAuthProvider
    ) -> str | None:
        token = self._store.get_token(session_id, provider)
        if not token:
            return None

        if self._is_expiring(token):
            refreshed = await self._refresh_token(session_id, provider, token)
            if not refreshed:
                self._store.remove_token(session_id, provider)
                return None
            token = refreshed

        return token.access_token

    async def _refresh_token(
        self,
        session_id: str,
        provider: OAuthProvider,
        token: OAuthTokenState,
    ) -> OAuthTokenState | None:
        if not token.refresh_token:
            return None

        metadata = await self._discovery.discover(provider)
        token_endpoint = metadata.authorization_server_metadata.get("token_endpoint")
        if not token_endpoint:
            return None

        client_registration = await self._resolve_client_registration(
            session_id=session_id,
            provider=provider,
            metadata=metadata.authorization_server_metadata,
        )

        data = {
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": client_registration.client_id,
        }
        if provider != OAuthProvider.ATLASSIAN and metadata.resource:
            data["resource"] = metadata.resource
        headers = {"Accept": "application/json"}

        if (
            client_registration.client_secret
            and client_registration.token_endpoint_auth_method == "client_secret_basic"
        ):
            basic_value = base64.b64encode(
                f"{client_registration.client_id}:{client_registration.client_secret}".encode(
                    "utf-8"
                )
            ).decode("ascii")
            headers["Authorization"] = f"Basic {basic_value}"
        elif client_registration.client_secret:
            data["client_secret"] = client_registration.client_secret

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                token_endpoint,
                headers=headers,
                data=data,
            )
            if response.status_code >= 400:
                return None
            payload = response.json()

        access_token = payload.get("access_token")
        if not access_token:
            return None

        expires_in = payload.get("expires_in")
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            if expires_in is not None
            else None
        )

        refreshed = OAuthTokenState(
            provider=provider,
            access_token=access_token,
            refresh_token=payload.get("refresh_token", token.refresh_token),
            token_type=payload.get("token_type", token.token_type),
            scope=payload.get("scope", token.scope),
            expires_at=expires_at,
            metadata=token.metadata,
        )
        self._store.save_token(session_id, refreshed)
        return refreshed

    async def _resolve_client_registration(
        self,
        session_id: str,
        provider: OAuthProvider,
        metadata: dict[str, Any],
    ) -> OAuthClientRegistration:
        existing = self._store.get_client_registration(session_id, provider)
        if existing:
            return existing

        preconfigured = self._preconfigured_clients.get(provider)
        if preconfigured:
            self._store.save_client_registration(session_id, provider, preconfigured)
            return preconfigured

        # Atlassian MCP OAuth/DCR flow was derived from:
        # https://benjamin-fuqua.medium.com/why-your-custom-oauth-tokens-fail-with-the-atlassian-mcp-server-and-how-dcr-fixes-it-2566b779f795
        # Prefer DCR and only allow static app credentials if explicitly enabled.
        if provider == OAuthProvider.ATLASSIAN:
            dcr_endpoint = metadata.get("registration_endpoint")
            if dcr_endpoint:
                registration = await self._try_dynamic_client_registration(
                    provider,
                    dcr_endpoint,
                )
                if registration:
                    self._store.save_client_registration(
                        session_id, provider, registration
                    )
                    return registration

            raise OAuthFlowError(
                "Atlassian MCP OAuth requires dynamic client registration (DCR), "
                "but registration failed or registration_endpoint was unavailable."
            )

        dcr_endpoint = metadata.get("registration_endpoint")
        if dcr_endpoint:
            registration = await self._try_dynamic_client_registration(
                provider,
                dcr_endpoint,
            )
            if registration:
                self._store.save_client_registration(session_id, provider, registration)
                return registration

        raise OAuthFlowError(self._missing_client_config_message(provider))

    async def _try_dynamic_client_registration(
        self,
        provider: OAuthProvider,
        registration_endpoint: str,
    ) -> OAuthClientRegistration | None:
        redirect_uri = f"{self._backend_base_url}/auth/{provider.value}/callback"
        token_endpoint_auth_method = (
            "client_secret_post" if provider == OAuthProvider.ATLASSIAN else "none"
        )
        payload = {
            "client_name": "Project Kraken MCP Client",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": token_endpoint_auth_method,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    registration_endpoint,
                    json=payload,
                    headers={"Accept": "application/json"},
                )
                if response.status_code >= 400:
                    return None
                body = response.json()
        except httpx.HTTPError:
            return None

        client_id = body.get("client_id")
        if not client_id:
            return None

        return OAuthClientRegistration(
            client_id=client_id,
            client_secret=body.get("client_secret"),
            token_endpoint_auth_method=body.get("token_endpoint_auth_method", "none"),
        )

    @staticmethod
    def _is_expiring(token: OAuthTokenState, skew_seconds: int = 90) -> bool:
        if not token.expires_at:
            return False
        return (
            datetime.now(timezone.utc) + timedelta(seconds=skew_seconds)
            >= token.expires_at
        )

    def callback_redirect_url(self, provider: OAuthProvider, status: str) -> str:
        params = urlencode({"provider": provider.value, "status": status})
        return f"{self._frontend_base_url}/?{params}"

    def callback_redirect_with_error(
        self,
        provider: OAuthProvider,
        status: str,
        error: str,
    ) -> str:
        params = urlencode(
            {
                "provider": provider.value,
                "status": status,
                "error": error,
            }
        )
        return f"{self._frontend_base_url}/?{params}"

    @staticmethod
    def _safe_response_detail(response: httpx.Response, max_len: int = 300) -> str:
        try:
            body = response.text.strip()
        except Exception:
            return ""

        if not body:
            return ""

        if len(body) > max_len:
            body = f"{body[:max_len]}..."
        return f"Response: {body}"

    @staticmethod
    def build_fallback_access_tokens_from_env() -> dict[OAuthProvider, str]:
        return build_fallback_access_tokens_from_env()

    @staticmethod
    def build_preconfigured_clients_from_env() -> dict[
        OAuthProvider, OAuthClientRegistration
    ]:
        return build_preconfigured_clients_from_env()

    @staticmethod
    def _missing_client_config_message(provider: OAuthProvider) -> str:
        if provider == OAuthProvider.GITHUB:
            return (
                "GitHub OAuth client is not configured. "
                "GitHub MCP currently advertises authorization server https://github.com/login/oauth "
                "without a dynamic client registration endpoint, so app credentials are required. "
                "Either configure a GitHub app OAuth client (GITHUB_OAUTH_CLIENT_ID / "
                "GITHUB_OAUTH_CLIENT_SECRET, aliases: GITHUB_APP_CLIENT_ID / "
                "GITHUB_APP_CLIENT_SECRET), or provide a service token fallback "
                "(GITHUB_SERVICE_ACCESS_TOKEN)."
            )

        if provider == OAuthProvider.ATLASSIAN:
            return (
                "Atlassian MCP OAuth requires dynamic client registration (DCR), "
                "but no registration endpoint was discovered."
            )

        return (
            "No dynamic registration available and no pre-registered client configured."
        )
