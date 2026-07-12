from typing import List

from haystack import Document, component


@component
class RegisterMCPSources:
    """Register a source retrieved via MCP tools as a Document for source tracking.

    The agent should call this tool after retrieving relevant information from MCP
    tools (GitHub, Jira, Confluence, etc.) so that the sources can be surfaced to
    the user alongside the answer, mirroring the RAG source-tracking behaviour.
    """

    @component.output_types(documents=List[Document])
    def run(
        self,
        title: str,
        url: str,
        content: str,
        source_type: str,
        last_updated: str = "",
        # JIRA-specific
        issue_key: str = "",
        project_key: str = "",
        # Confluence-specific
        page_id: str = "",
        space_key: str = "",
        # GitHub-specific
        repo_name: str = "",
        file_path: str = "",
        commit_hash: str = "",
        ref: str = "",
    ) -> dict:
        meta: dict = {
            "title": title,
            "source": url,
            "type": source_type,
            "last_updated": last_updated,
        }
        if source_type == "JIRA":
            meta["issue_key"] = issue_key
            meta["project_key"] = project_key
        elif source_type == "CONFLUENCE":
            meta["page_id"] = page_id
            meta["space_key"] = space_key
        elif source_type == "GITHUB":
            meta["repo_name"] = repo_name
            meta["file_path"] = file_path
            meta["commit_hash"] = commit_hash
            meta["ref"] = ref
        doc = Document(content=content, meta=meta)
        return {"documents": [doc]}
