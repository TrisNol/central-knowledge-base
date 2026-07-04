import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from src.api import api_router
from src.config import AppContainer, load_env_config
from src.core.auth import (
    MCPOAuthDiscoveryService,
    OAuthProvider,
    OAuthService,
    OAuthSessionStore,
)
from src.core.chat_memory import ChatMemory
from src.core.session_agent_manager import SessionAgentManager
from src.tools.mcp_oauth_tools import provider_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI):
    container: AppContainer = app.container
    loaders = app.state.loaders
    pipelines = app.state.pipelines

    # Init loaders
    loaders["jira"] = container.jira_loader()
    loaders["confluence"] = container.confluence_loader()
    loaders["github"] = container.github_loader()

    pipelines["index"] = container.knowledge_index()
    pipelines["graph"] = container.knowledge_graph_service()

    oauth_store = OAuthSessionStore(pending_ttl_seconds=600)
    discovery = MCPOAuthDiscoveryService(
        provider_endpoints={
            OAuthProvider.GITHUB: provider_endpoint(OAuthProvider.GITHUB),
            OAuthProvider.ATLASSIAN: provider_endpoint(OAuthProvider.ATLASSIAN),
        },
        fallback_authorization_servers={
            OAuthProvider.GITHUB: container.config.oauth.github_authorization_server(),
            OAuthProvider.ATLASSIAN: container.config.oauth.atlassian_authorization_server(),
        },
    )
    oauth_service = OAuthService(
        session_store=oauth_store,
        discovery_service=discovery,
        frontend_base_url=container.config.auth.frontend_base_url(),
        backend_base_url=container.config.auth.backend_base_url(),
        provider_scopes={
            OAuthProvider.GITHUB: container.config.oauth.github_scope(),
            OAuthProvider.ATLASSIAN: container.config.oauth.atlassian_scope(),
        },
        fallback_access_tokens=OAuthService.build_fallback_access_tokens_from_env(),
        preconfigured_clients=OAuthService.build_preconfigured_clients_from_env(),
    )
    app.state.oauth_service = oauth_service
    app.state.session_agent_manager = SessionAgentManager(
        oauth_service=oauth_service,
        llm_generator_factory=container.llm_generator,
        is_dev=container.config.app.environment() == "development",
        rag_search=container.rag_search(),
        graph_query=container.graph_query(),
        fetch_neighbors=container.fetch_neighbors(),
    )

    yield

    # Clean up before shutdown
    app.state.session_agent_manager.clear_all()
    pipelines.clear()
    loaders.clear()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.container = AppContainer()
    app.container.config.from_dict(load_env_config())
    app.state.pipelines = {}
    app.state.loaders = {}
    app.state.chat_memory = ChatMemory(max_messages_per_session=50)
    return app


app = create_app()
origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Check if session ID exists in cookies
        session_id = request.cookies.get("X-Session-ID")

        # Generate new session ID if not present
        if not session_id:
            session_id = str(uuid.uuid4())

        # Store session ID in request state for potential use in endpoints
        request.state.session_id = session_id

        # Call the next middleware/endpoint
        response = await call_next(request)

        # Set the session ID cookie on the response
        response.set_cookie(
            key="X-Session-ID",
            value=session_id,
            httponly=True,
            samesite="lax",
            secure=False,  # Set to True in production with HTTPS
            max_age=86400 * 30,  # 30 days
        )

        # Also set it as a response header for visibility
        response.headers["X-Session-ID"] = session_id

        return response


app.add_middleware(SessionMiddleware)

app.include_router(api_router)
