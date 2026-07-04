from __future__ import annotations

import hashlib
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

from haystack.components.generators.utils import print_streaming_chunk
from haystack.tools import ComponentTool

from src.agents import MCPAgent, RAGAgent
from src.common.models import ChatMode, MCPAuthType
from src.core.auth.models import OAuthProvider
from src.core.auth.oauth_service import OAuthService
from src.tools.filter_docs_tool import FilterDocs
from src.tools.mcp_oauth_tools import create_oauth_mcp_toolset
from src.tools.utils import _docs_to_summary

if TYPE_CHECKING:
    from haystack.components.agents import Agent

    from src.tools.fetch_neighbors_tool import FetchNeighbors
    from src.tools.graph_query_tool import GraphQuery
    from src.tools.rag_search_tool import RAGSearch


@dataclass
class _SessionAgentEntry:
    signature: str
    agent: Agent
    toolsets: list
    mode: ChatMode
    mcp_auth_type: MCPAuthType | None = None


class SessionAgentManager:
    def __init__(
        self,
        oauth_service: OAuthService,
        llm_generator_factory,
        is_dev: bool,
        rag_search: RAGSearch | None = None,
        graph_query: GraphQuery | None = None,
        fetch_neighbors: FetchNeighbors | None = None,
    ):
        self._oauth_service = oauth_service
        self._llm_generator_factory = llm_generator_factory
        self._is_dev = is_dev
        self._rag_search = rag_search
        self._graph_query = graph_query
        self._fetch_neighbors = fetch_neighbors
        self._lock = Lock()
        self._agents: dict[str, _SessionAgentEntry] = {}

    async def get_or_create_agent(
        self,
        session_id: str,
        chat_mode: ChatMode = ChatMode.MCP,
        mcp_auth_type: MCPAuthType = MCPAuthType.OAUTH,
    ) -> Agent:
        """Get or create an agent for the session based on the specified mode and auth type."""
        if chat_mode == ChatMode.RAG:
            return self._get_or_create_rag_agent(session_id)
        else:
            return await self._get_or_create_mcp_agent(session_id, mcp_auth_type)

    def _get_or_create_rag_agent(self, session_id: str) -> RAGAgent:
        """Create a RAG agent using the knowledge graph search tool."""
        if not self._rag_search:
            raise ValueError("RAG search tool not available")

        signature = "rag"  # RAG agents are stateless

        with self._lock:
            existing = self._agents.get(session_id)
            if (
                existing
                and existing.signature == signature
                and existing.mode == ChatMode.RAG
            ):
                return existing.agent

        rag_tool = ComponentTool(
            component=self._rag_search,
            name="rag_search_tool",
            description="Semantic search across all indexed documents (Jira, Confluence, GitHub). Use this for broad or conceptual questions where the user describes a topic, problem, or concept in natural language (e.g. 'How does our authentication flow work?', 'What is the deployment process?').",
            inputs_from_state={"allowed_sources": "allowed_sources"},
            outputs_to_state={"documents": {"source": "documents"}},
            outputs_to_string={"source": "documents", "handler": _docs_to_summary},
        )

        tools = [rag_tool]

        if self._graph_query:
            graph_query_tool = ComponentTool(
                component=self._graph_query,
                name="graph_query_tool",
                description="Direct property lookup in the knowledge graph. Use this when the user mentions a specific identifier such as a Jira ticket key (e.g. 'DEV-42'), a Confluence space key, a project key, a GitHub repo name, or a file path. Fast and precise — best for targeted lookups by known names or keys.",
                inputs_from_state={"allowed_sources": "allowed_sources"},
                outputs_to_state={"documents": {"source": "documents"}},
                outputs_to_string={"source": "documents", "handler": _docs_to_summary},
            )
            tools.append(graph_query_tool)

        filter_docs_tool = ComponentTool(
            component=FilterDocs(),
            name="filter_docs_tool",
            description="Filter the documents already retrieved in the current conversation. Use this AFTER rag_search_tool or graph_query_tool when the initial search returned too many results and you need to narrow them down to only the most relevant ones for the user's question.",
            inputs_from_state={"documents": "documents"},
            outputs_to_state={"documents": {"source": "documents"}},
            outputs_to_string={"source": "documents", "handler": _docs_to_summary},
        )
        tools.append(filter_docs_tool)

        if self._fetch_neighbors:
            fetch_neighbors_tool = ComponentTool(
                component=self._fetch_neighbors,
                name="fetch_neighbors_tool",
                description="Expand context by fetching documents linked to the ones already retrieved via REFERENCES relationships in the graph. Use this AFTER an initial search when the user asks about related items, dependencies, or you need more surrounding context (e.g. 'What tickets are related to DEV-42?', 'Show me linked Confluence pages').",
                inputs_from_state={
                    "documents": "documents",
                    "allowed_sources": "allowed_sources",
                },
                outputs_to_state={"documents": {"source": "documents"}},
                outputs_to_string={"source": "documents", "handler": _docs_to_summary},
            )
            tools.append(fetch_neighbors_tool)

        agent = RAGAgent(
            chat_generator=self._llm_generator_factory(),
            tools=tools,
            streaming_callback=print_streaming_chunk if self._is_dev else None,
        )

        with self._lock:
            old_entry = self._agents.get(session_id)
            self._agents[session_id] = _SessionAgentEntry(
                signature=signature,
                agent=agent,
                toolsets=[],
                mode=ChatMode.RAG,
            )

        if old_entry:
            self._close_toolsets(old_entry.toolsets)

        return agent

    async def _get_or_create_mcp_agent(
        self, session_id: str, mcp_auth_type: MCPAuthType
    ) -> MCPAgent:
        """Create an MCP agent with either OAuth or service credentials."""
        provider_tokens: list[tuple[OAuthProvider, str]] = []

        if mcp_auth_type == MCPAuthType.OAUTH:
            # Get OAuth tokens for each provider
            for provider in OAuthProvider:
                token = await self._oauth_service.get_valid_access_token(
                    session_id, provider
                )
                if token:
                    provider_tokens.append((provider, token))
        else:
            # Service credentials - get fallback tokens
            fallback_tokens = self._oauth_service.get_fallback_access_tokens()
            for provider, token in fallback_tokens.items():
                if token:
                    provider_tokens.append((provider, token))

        signature = self._signature(provider_tokens, mcp_auth_type)

        with self._lock:
            existing = self._agents.get(session_id)
            if (
                existing
                and existing.signature == signature
                and existing.mode == ChatMode.MCP
                and existing.mcp_auth_type == mcp_auth_type
            ):
                return existing.agent

        toolsets = [
            create_oauth_mcp_toolset(provider, token)
            for provider, token in provider_tokens
        ]

        agent = MCPAgent(
            chat_generator=self._llm_generator_factory(),
            tools=toolsets,
            streaming_callback=print_streaming_chunk if self._is_dev else None,
        )

        with self._lock:
            old_entry = self._agents.get(session_id)
            self._agents[session_id] = _SessionAgentEntry(
                signature=signature,
                agent=agent,
                toolsets=toolsets,
                mode=ChatMode.MCP,
                mcp_auth_type=mcp_auth_type,
            )

        if old_entry:
            self._close_toolsets(old_entry.toolsets)

        return agent

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            entry = self._agents.pop(session_id, None)
        if entry:
            self._close_toolsets(entry.toolsets)

    def clear_all(self) -> None:
        with self._lock:
            entries = list(self._agents.values())
            self._agents.clear()
        for entry in entries:
            self._close_toolsets(entry.toolsets)

    @staticmethod
    def _signature(
        provider_tokens: list[tuple[OAuthProvider, str]], mcp_auth_type: MCPAuthType
    ) -> str:
        if not provider_tokens:
            return f"{mcp_auth_type.value}:empty"

        payload = "|".join(
            f"{provider.value}:{hashlib.sha256(token.encode('utf-8')).hexdigest()}"
            for provider, token in sorted(
                provider_tokens, key=lambda item: item[0].value
            )
        )
        return f"{mcp_auth_type.value}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _close_toolsets(toolsets: list) -> None:
        for toolset in toolsets:
            try:
                toolset.close()
            except Exception:
                # Ignore close errors during cleanup.
                pass
