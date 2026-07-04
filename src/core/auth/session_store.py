from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock

from src.core.auth.models import (
    OAuthClientRegistration,
    OAuthProvider,
    OAuthTokenState,
    PendingOAuthState,
    ProviderConnectionStatus,
    SessionAuthState,
)


class OAuthSessionStore:
    """Thread-safe in-memory OAuth state keyed by app session ID."""

    def __init__(self, pending_ttl_seconds: int = 600):
        self._lock = Lock()
        self._pending_ttl = timedelta(seconds=pending_ttl_seconds)
        self._sessions: dict[str, SessionAuthState] = {}

    def _ensure_session(self, session_id: str) -> SessionAuthState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionAuthState()
        return self._sessions[session_id]

    def save_pending(self, session_id: str, pending: PendingOAuthState) -> None:
        with self._lock:
            session = self._ensure_session(session_id)
            session.pending[pending.state] = pending

    def pop_pending(self, session_id: str, state: str) -> PendingOAuthState | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            pending = session.pending.pop(state, None)
            if not pending:
                return None

            now = datetime.now(timezone.utc)
            if now - pending.created_at > self._pending_ttl:
                return None

            return pending

    def save_token(self, session_id: str, token: OAuthTokenState) -> None:
        with self._lock:
            session = self._ensure_session(session_id)
            session.tokens[token.provider] = token

    def get_token(
        self, session_id: str, provider: OAuthProvider
    ) -> OAuthTokenState | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.tokens.get(provider)

    def remove_token(self, session_id: str, provider: OAuthProvider) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.tokens.pop(provider, None)
                session.clients.pop(provider, None)

    def save_client_registration(
        self,
        session_id: str,
        provider: OAuthProvider,
        registration: OAuthClientRegistration,
    ) -> None:
        with self._lock:
            session = self._ensure_session(session_id)
            session.clients[provider] = registration

    def get_client_registration(
        self,
        session_id: str,
        provider: OAuthProvider,
    ) -> OAuthClientRegistration | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.clients.get(provider)

    def statuses(self, session_id: str) -> list[ProviderConnectionStatus]:
        with self._lock:
            session = self._sessions.get(session_id)
            tokens = session.tokens if session else {}

            statuses: list[ProviderConnectionStatus] = []
            for provider in OAuthProvider:
                token = tokens.get(provider)
                statuses.append(
                    ProviderConnectionStatus(
                        provider=provider,
                        connected=token is not None,
                        expires_at=token.expires_at if token else None,
                        scope=token.scope if token else None,
                    )
                )
            return statuses

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
