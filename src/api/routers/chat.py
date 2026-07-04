import logging

from fastapi import APIRouter, HTTPException, Request
from haystack.dataclasses import ChatMessage
from pydantic import BaseModel, Field

from src.common.models import (
    BaseMetadata,
    ChatMode,
    ConfluenceMetadata,
    DocumentSourceType,
    GitHubMetadata,
    JiraMetadata,
    MCPAuthType,
    ResponseModel,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class AskRequest(BaseModel):
    question: str
    sources: list[str] = Field(default_factory=list)
    chat_mode: ChatMode = Field(
        default=ChatMode.MCP, description="Chat mode: 'rag' or 'mcp'"
    )
    mcp_auth_type: MCPAuthType = Field(
        default=MCPAuthType.OAUTH,
        description="MCP authentication type: 'oauth' or 'service_credentials'",
    )


def _normalize_requested_sources(sources: list[str] | None) -> list[str]:
    if not sources:
        return []

    allowed_values = {source.value for source in DocumentSourceType}
    normalized: list[str] = []
    for source in sources:
        source_value = source.strip().upper()
        if not source_value:
            continue
        if source_value not in allowed_values:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid source '{source}'. "
                    f"Allowed values: {', '.join(sorted(allowed_values))}"
                ),
            )
        if source_value not in normalized:
            normalized.append(source_value)
    return normalized


def _map_metadata(meta: dict) -> BaseMetadata:
    doc_type = meta.get("type")
    if doc_type == "JIRA":
        return JiraMetadata(**meta)
    if doc_type == "CONFLUENCE":
        return ConfluenceMetadata(**meta)
    if doc_type == "GITHUB":
        return GitHubMetadata(**meta)
    raise ValueError(f"Unknown document type: {doc_type}")


@router.post("/ask", response_model=ResponseModel)
async def answer_question(body: AskRequest, request: Request) -> ResponseModel:
    chat_memory = request.app.state.chat_memory
    agent_manager = request.app.state.session_agent_manager

    session_id = request.state.session_id
    logger.info(
        "[Session ID: %s] Received question: %s with sources: %s (mode: %s, auth: %s)",
        session_id,
        body.question,
        body.sources,
        body.chat_mode,
        body.mcp_auth_type,
    )

    chat_memory.add_message(session_id, "user", body.question)
    allowed_sources = _normalize_requested_sources(body.sources)

    session_state = chat_memory.get_agent_state(session_id)
    session_documents = session_state.get("documents", [])
    if allowed_sources:
        session_documents = [
            doc
            for doc in session_documents
            if str(doc.meta.get("type", "")).upper() in allowed_sources
        ]

    session_messages = session_state["messages"] + [
        ChatMessage.from_user(body.question)
    ]

    agent = await agent_manager.get_or_create_agent(
        session_id,
        chat_mode=body.chat_mode,
        mcp_auth_type=body.mcp_auth_type,
    )

    result = agent.run(
        messages=session_messages,
        documents=session_documents,
        allowed_sources=allowed_sources,
    )

    result_documents = result.get("documents", [])
    if allowed_sources:
        result_documents = [
            doc
            for doc in result_documents
            if str(doc.meta.get("type", "")).upper() in allowed_sources
        ]

    sources_dict = [_map_metadata(doc.meta).model_dump() for doc in result_documents]

    chat_memory.add_message(
        session_id,
        "assistant",
        result["last_message"].text,
        sources_dict,
    )
    chat_memory.set_agent_state(
        session_id,
        messages=result["messages"],
        documents=result_documents,
    )

    return {
        "answer": result["last_message"].text,
        "source_documents": sources_dict,
    }


@router.get("/chat/history")
async def get_chat_history(request: Request) -> dict:
    session_id = request.state.session_id
    chat_memory = request.app.state.chat_memory
    history = chat_memory.get_history(session_id)

    return {
        "session_id": session_id,
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "sources": msg.sources,
            }
            for msg in history
        ],
    }


@router.post("/chat/clear")
async def clear_chat_history(request: Request) -> dict[str, str]:
    session_id = request.state.session_id
    chat_memory = request.app.state.chat_memory
    agent_manager = request.app.state.session_agent_manager

    chat_memory.clear_session(session_id)
    agent_manager.clear_session(session_id)
    logger.info("[Session ID: %s] Chat history cleared", session_id)

    return {"status": "cleared", "session_id": session_id}
