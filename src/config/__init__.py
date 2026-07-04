import os

from dependency_injector import containers, providers
from dotenv import load_dotenv

from src.core.atlassian.confluence_loader import ConfluenceLoader
from src.core.atlassian.jira_loader import JiraLoader
from src.core.auth.models import OAuthClientRegistration, OAuthProvider
from src.core.chunk_retriever import ChunkRetriever
from src.core.document_chunk_writer import DocumentChunkWriter
from src.core.git.github_loader import GitHubLoader
from src.core.knowledge_graph_service import KnowledgeGraphService
from src.core.knowledge_index import KnowledgeIndex
from src.core.relationship_manager import RelationshipManager
from src.core.settings import (
    create_document_embedder,
    create_llm_generator,
    create_text_embedder,
)
from src.tools.fetch_neighbors_tool import FetchNeighbors
from src.tools.graph_query_tool import GraphQuery
from src.tools.rag_search_tool import RAGSearch


def _comma_separated_values_env(key: str) -> list[str]:
    value = os.getenv(key, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def build_fallback_access_tokens_from_env() -> dict[OAuthProvider, str]:
    result: dict[OAuthProvider, str] = {}

    github_token = (
        os.getenv("GITHUB_SERVICE_ACCESS_TOKEN")
        or os.getenv("GITHUB_ACCESS_TOKEN")
        or os.getenv("MCP_GITHUB_ACCESS_TOKEN")
    )
    if github_token:
        result[OAuthProvider.GITHUB] = github_token

    atlassian_token = (
        os.getenv("ATLASSIAN_SERVICE_ACCESS_TOKEN")
        or os.getenv("ATLASSIAN_ACCESS_TOKEN")
        or os.getenv("MCP_ATLASSIAN_ACCESS_TOKEN")
    )
    if atlassian_token:
        result[OAuthProvider.ATLASSIAN] = atlassian_token

    return result


def build_preconfigured_clients_from_env() -> dict[
    OAuthProvider, OAuthClientRegistration
]:
    clients: dict[OAuthProvider, OAuthClientRegistration] = {}

    github_client_id = os.getenv("GITHUB_OAUTH_CLIENT_ID") or os.getenv(
        "GITHUB_APP_CLIENT_ID"
    )
    github_client_secret = os.getenv("GITHUB_OAUTH_CLIENT_SECRET") or os.getenv(
        "GITHUB_APP_CLIENT_SECRET"
    )
    if github_client_id and github_client_secret:
        clients[OAuthProvider.GITHUB] = OAuthClientRegistration(
            client_id=github_client_id,
            client_secret=github_client_secret,
            token_endpoint_auth_method="client_secret_post",
        )

    return clients


def load_env_config() -> dict:
    """Load all runtime settings from environment in one place."""
    load_dotenv()
    chat_provider = os.getenv("LLM_CHAT_PROVIDER", "ollama").lower()
    embedding_provider = os.getenv("LLM_EMBEDDING_PROVIDER", chat_provider).lower()

    return {
        "app": {
            "environment": os.getenv("ENV", "production"),
            "port": int(os.getenv("PORT", 8000)),
        },
        "auth": {
            "frontend_base_url": os.getenv(
                "AUTH_FRONTEND_BASE_URL", "http://localhost:4200"
            ),
            "backend_base_url": os.getenv(
                "AUTH_BACKEND_BASE_URL", "http://localhost:8000"
            ),
        },
        "jira": {
            "url": os.getenv("JIRA_URL"),
            "username": os.getenv("JIRA_USERNAME"),
            "api_key": os.getenv("JIRA_API_KEY"),
            "projects": _comma_separated_values_env("JIRA_PROJECTS"),
        },
        "confluence": {
            "url": os.getenv("CONFLUENCE_URL"),
            "username": os.getenv("CONFLUENCE_USERNAME"),
            "api_key": os.getenv("CONFLUENCE_API_KEY"),
            "spaces": _comma_separated_values_env("CONFLUENCE_SPACES"),
        },
        "github": {
            "repositories": _comma_separated_values_env("GITHUB_REPOSITORIES"),
            "ref": os.getenv("GITHUB_REF", "main"),
            "token": os.getenv("GITHUB_TOKEN"),
        },
        "neo4j": {
            "url": os.getenv("NEO4J_URL"),
            "username": os.getenv("NEO4J_USERNAME"),
            "password": os.getenv("NEO4J_PASSWORD"),
            "database": os.getenv("NEO4J_DATABASE", "neo4j"),
            "index": os.getenv("NEO4J_INDEX", "chunk_embeddings"),
            "top_k": int(os.getenv("NEO4J_TOP_K", "5")),
        },
        "embedding": {
            "dimension": int(os.getenv("EMBEDDING_DIMENSION", "768")),
        },
        "llm": {
            "chat_provider": chat_provider,
            "embedding_provider": embedding_provider,
            "chat_model": os.getenv("LLM_CHAT_MODEL"),
            "embedding_model": os.getenv("LLM_EMBEDDING_MODEL"),
            "host": os.getenv("LLM_HOST"),
            "openai_api_key": os.getenv("OPENAI_API_KEY"),
            "azure_deployment_name": os.getenv("AZURE_DEPLOYMENT_NAME"),
            "azure_openai_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT"),
            "azure_openai_api_key": os.getenv("AZURE_OPENAI_API_KEY"),
            "azure_openai_api_version": os.getenv("AZURE_OPENAI_API_VERSION"),
        },
        "oauth": {
            "github_authorization_server": os.getenv(
                "GITHUB_OAUTH_AUTHORIZATION_SERVER",
                "https://github.com/login/oauth",
            ),
            "atlassian_authorization_server": os.getenv(
                "ATLASSIAN_OAUTH_AUTHORIZATION_SERVER",
                "https://mcp.atlassian.com",
            ),
            "github_scope": os.getenv("GITHUB_OAUTH_SCOPE", "read:user repo"),
            "atlassian_scope": os.getenv(
                "ATLASSIAN_OAUTH_SCOPE",
                "offline_access read:confluence-user read:jira-work read:me search:confluence",
            ),
        },
    }


class AppContainer(containers.DeclarativeContainer):
    """Application dependency container."""

    config = providers.Configuration()

    jira_loader = providers.Factory(
        JiraLoader,
        url=config.jira.url,
        username=config.jira.username,
        api_key=config.jira.api_key,
        projects=config.jira.projects,
    )
    confluence_loader = providers.Factory(
        ConfluenceLoader,
        url=config.confluence.url,
        username=config.confluence.username,
        api_key=config.confluence.api_key,
        spaces=config.confluence.spaces,
    )
    github_loader = providers.Factory(
        GitHubLoader,
        repositories=config.github.repositories,
        ref=config.github.ref,
        token=config.github.token,
    )

    chunk_writer = providers.Factory(
        DocumentChunkWriter,
        neo4j_url=config.neo4j.url,
        neo4j_username=config.neo4j.username,
        neo4j_password=config.neo4j.password,
        neo4j_database=config.neo4j.database,
        embedding_dim=config.embedding.dimension,
    )
    chunk_retriever = providers.Factory(
        ChunkRetriever,
        neo4j_url=config.neo4j.url,
        neo4j_username=config.neo4j.username,
        neo4j_password=config.neo4j.password,
        neo4j_database=config.neo4j.database,
        index_name=config.neo4j.index,
        top_k=config.neo4j.top_k,
    )
    relationship_manager = providers.Factory(
        RelationshipManager,
        neo4j_url=config.neo4j.url,
        neo4j_username=config.neo4j.username,
        neo4j_password=config.neo4j.password,
        neo4j_database=config.neo4j.database,
    )
    knowledge_graph_service = providers.Factory(
        KnowledgeGraphService,
        neo4j_url=config.neo4j.url,
        neo4j_username=config.neo4j.username,
        neo4j_password=config.neo4j.password,
        neo4j_database=config.neo4j.database,
    )

    llm_generator = providers.Factory(
        create_llm_generator,
        provider=config.llm.chat_provider,
        model=config.llm.chat_model,
        host=config.llm.host,
        openai_api_key=config.llm.openai_api_key,
        azure_deployment_name=config.llm.azure_deployment_name,
        azure_openai_endpoint=config.llm.azure_openai_endpoint,
        azure_openai_api_key=config.llm.azure_openai_api_key,
    )
    document_embedder = providers.Factory(
        create_document_embedder,
        provider=config.llm.embedding_provider,
        model=config.llm.embedding_model,
        host=config.llm.host,
        openai_api_key=config.llm.openai_api_key,
        azure_openai_endpoint=config.llm.azure_openai_endpoint,
        azure_openai_api_key=config.llm.azure_openai_api_key,
        azure_openai_api_version=config.llm.azure_openai_api_version,
        embedding_dimension=config.embedding.dimension,
    )
    text_embedder = providers.Factory(
        create_text_embedder,
        provider=config.llm.embedding_provider,
        model=config.llm.embedding_model,
        host=config.llm.host,
        openai_api_key=config.llm.openai_api_key,
        azure_openai_endpoint=config.llm.azure_openai_endpoint,
        azure_openai_api_key=config.llm.azure_openai_api_key,
        azure_openai_api_version=config.llm.azure_openai_api_version,
        embedding_dimension=config.embedding.dimension,
    )

    knowledge_index = providers.Factory(
        KnowledgeIndex,
        chunk_writer=chunk_writer,
        document_embedder=document_embedder,
        relationship_manager=relationship_manager,
    )

    rag_search = providers.Factory(
        RAGSearch,
        embedding_retriever=chunk_retriever,
        text_embedder=text_embedder,
    )
    graph_query = providers.Factory(
        GraphQuery,
        neo4j_url=config.neo4j.url,
        neo4j_username=config.neo4j.username,
        neo4j_password=config.neo4j.password,
        neo4j_database=config.neo4j.database,
        chat_generator=llm_generator,
    )
    fetch_neighbors = providers.Factory(
        FetchNeighbors,
        neo4j_url=config.neo4j.url,
        neo4j_username=config.neo4j.username,
        neo4j_password=config.neo4j.password,
        neo4j_database=config.neo4j.database,
    )
