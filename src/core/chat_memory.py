from collections import defaultdict
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatHistoryMessage(BaseModel):
    """Represents a single message in the chat history"""

    role: str = Field(..., description="Role of the message sender (user or assistant)")
    content: str = Field(..., description="Content of the message")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the message was created",
    )
    sources: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Source documents used for this message"
    )


class SessionMemory(BaseModel):
    """Represents all in-memory data tracked for a session."""

    history: List[ChatHistoryMessage] = Field(default_factory=list)
    messages: List[Any] = Field(default_factory=list)
    documents: List[Any] = Field(default_factory=list)


class ChatMemory:
    """Thread-safe in-memory storage for chat + agent session state."""

    def __init__(self, max_messages_per_session: int = 50):
        self._memory: Dict[str, SessionMemory] = defaultdict(SessionMemory)
        self._lock = Lock()
        self.max_messages_per_session = max_messages_per_session

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sources: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Add a message to the chat history for a given session.

        Args:
            session_id: The session identifier
            role: The role of the sender ('user' or 'assistant')
            content: The message content
            sources: Optional list of source documents used for this message
        """
        with self._lock:
            message = ChatHistoryMessage(role=role, content=content, sources=sources)
            self._memory[session_id].history.append(message)

            # Keep only the last N messages to prevent unlimited growth
            if len(self._memory[session_id].history) > self.max_messages_per_session:
                self._memory[session_id].history = self._memory[session_id].history[
                    -self.max_messages_per_session :
                ]

    def get_history(
        self, session_id: str, limit: Optional[int] = None
    ) -> List[ChatHistoryMessage]:
        """
        Retrieve chat history for a given session.

        Args:
            session_id: The session identifier
            limit: Optional limit on number of messages to return (most recent)

        Returns:
            List of chat history messages
        """
        with self._lock:
            session = self._memory.get(session_id)
            if session is None:
                return []
            messages = session.history
            if limit:
                return messages[-limit:]
            return messages.copy()

    def get_agent_state(self, session_id: str) -> Dict[str, List[Any]]:
        """
        Retrieve state used by the multi-turn agent pipeline.

        Args:
            session_id: The session identifier

        Returns:
            Dict containing `messages` and `documents` arrays
        """
        with self._lock:
            session = self._memory.get(session_id)
            if session is None:
                return {"messages": [], "documents": []}
            return {
                "messages": session.messages.copy(),
                "documents": session.documents.copy(),
            }

    def set_agent_state(
        self, session_id: str, messages: List[Any], documents: List[Any]
    ) -> None:
        """
        Update state used by the multi-turn agent pipeline.

        Args:
            session_id: The session identifier
            messages: Serialized agent message state
            documents: Documents retained for follow-up turns
        """
        with self._lock:
            session = self._memory[session_id]
            session.messages = messages.copy()
            session.documents = documents.copy()

    def clear_session(self, session_id: str) -> None:
        """
        Clear chat history for a specific session.

        Args:
            session_id: The session identifier
        """
        with self._lock:
            if session_id in self._memory:
                del self._memory[session_id]

    def clear_all(self) -> None:
        """Clear all chat histories"""
        with self._lock:
            self._memory.clear()
