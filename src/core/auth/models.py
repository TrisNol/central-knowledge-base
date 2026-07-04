from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class OAuthProvider(StrEnum):
    GITHUB = "github"
    ATLASSIAN = "atlassian"


class PendingOAuthState(BaseModel):
    provider: OAuthProvider
    state: str
    code_verifier: str
    redirect_uri: str
    nonce: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OAuthTokenState(BaseModel):
    provider: OAuthProvider
    access_token: str
    token_type: str = "Bearer"
    refresh_token: str | None = None
    scope: str | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderConnectionStatus(BaseModel):
    provider: OAuthProvider
    connected: bool
    connection_type: Literal["oauth", "fallback", "none"] = "none"
    expires_at: datetime | None = None
    scope: str | None = None


class ProviderDiscoveryMetadata(BaseModel):
    provider: OAuthProvider
    mcp_url: str
    resource: str | None = None
    resource_metadata_url: str
    resource_metadata: dict[str, Any]
    authorization_server: str
    authorization_server_metadata: dict[str, Any]


class OAuthClientRegistration(BaseModel):
    client_id: str
    client_secret: str | None = None
    token_endpoint_auth_method: str = "none"


class SessionAuthState(BaseModel):
    pending: dict[str, PendingOAuthState] = Field(default_factory=dict)
    tokens: dict[OAuthProvider, OAuthTokenState] = Field(default_factory=dict)
    clients: dict[OAuthProvider, OAuthClientRegistration] = Field(default_factory=dict)
