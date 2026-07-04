from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class DocumentSourceType(str, Enum):
    JIRA = "JIRA"
    CONFLUENCE = "CONFLUENCE"
    GITHUB = "GITHUB"


class ChatMode(str, Enum):
    """Chat mode selection: RAG (knowledge graph) or MCP (external tools)"""

    RAG = "rag"
    MCP = "mcp"


class MCPAuthType(str, Enum):
    """Authentication type for MCP mode"""

    OAUTH = "oauth"
    SERVICE_CREDENTIALS = "service_credentials"


class BaseMetadata(BaseModel):
    source: str = Field(..., description="Source of the document")
    type: DocumentSourceType = Field(..., description="Type of the document source")
    last_updated: str = Field(..., description="Last updated timestamp")
    links: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Extracted links and references (temporary, used only for relationship creation, not persisted)",
    )


class JiraMetadata(BaseMetadata):
    issue_key: str = Field(..., description="JIRA issue key")
    project_key: str = Field(..., description="JIRA project key")
    title: str = Field(..., description="Title of the JIRA issue")


class ConfluenceMetadata(BaseMetadata):
    page_id: str = Field(..., description="Confluence page ID")
    space_key: str = Field(..., description="Confluence space key")
    title: str = Field(..., description="Title of the Confluence page")


class GitHubMetadata(BaseMetadata):
    repo_name: str = Field(..., description="GitHub repository name")
    file_path: str = Field(..., description="Path to the file in the repository")
    commit_hash: str = Field(..., description="Commit hash of the file version")
    ref: str = Field(..., description="Branch or tag reference")


class ResponseModel(BaseModel):
    answer: str = Field(..., description="Answer to the question")
    source_documents: List[Union[JiraMetadata, ConfluenceMetadata, GitHubMetadata]] = (
        Field(
            ...,
            description="List of source documents used to generate the answer, with metadata based on document type",
        )
    )


class GraphNode(BaseModel):
    id: str = Field(..., description="Unique identifier for the node")
    title: str = Field(..., description="Display title for the node")
    url: str = Field(..., description="Link to the original source")
    type: DocumentSourceType = Field(..., description="Type of the document source")
    metadata: Union[JiraMetadata, ConfluenceMetadata, GitHubMetadata] = Field(
        ..., description="Node metadata"
    )


class GraphEdge(BaseModel):
    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")
    relationship: str = Field(..., description="Type of relationship")


class GraphResponse(BaseModel):
    nodes: List[GraphNode] = Field(..., description="List of nodes in the graph")
    edges: List[GraphEdge] = Field(..., description="List of edges connecting nodes")
