"""Automatic extraction of Haystack Documents from MCP tool result messages.

This module removes the need for the LLM to explicitly call
``register_mcp_sources_tool`` by parsing tool result messages produced during
``agent.run()`` and converting recognised MCP payloads (GitHub, Jira,
Confluence) into ``Document`` objects that can be surfaced as sources.
"""

from __future__ import annotations

import json
import logging
from typing import List
from urllib.parse import urlparse

from haystack import Document
from haystack.dataclasses import ChatMessage, ChatRole
from haystack.dataclasses.chat_message import TextContent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool-name → source-type mapping.
#
# Matching uses substring containment (``_matches_any``) so that both plain
# tool names and namespaced variants (e.g. ``atlassian_searchJiraIssuesUsingJql``
# or ``mcp_github_search_repositories``) are recognised without maintaining a
# separate list per namespace.
#
# NOTE: ``search_issues`` is intentionally absent from ``_JIRA_TOOLS`` because
# it is also a common GitHub tool name.  Atlassian Jira MCP uses the
# unambiguous camelCase name ``searchJiraIssuesUsingJql``.
# ---------------------------------------------------------------------------
_GITHUB_REPO_TOOLS: frozenset[str] = frozenset(
    {"search_repositories", "list_repositories", "get_repository"}
)
_JIRA_TOOLS: frozenset[str] = frozenset({"searchJiraIssuesUsingJql", "getJiraIssue"})
_CONFLUENCE_TOOLS: frozenset[str] = frozenset(
    {"searchConfluenceUsingCql", "getConfluencePage", "getPagesInConfluenceSpace"}
)
_ATLASSIAN_RESOURCES_TOOLS: frozenset[str] = frozenset(
    {"getAccessibleAtlassianResources"}
)


def _matches_any(tool_name: str, names: frozenset[str]) -> bool:
    """Return True if *any* canonical name is a substring of ``tool_name``.

    This handles both plain names (``searchJiraIssuesUsingJql``) and
    namespaced variants (``atlassian_searchJiraIssuesUsingJql``).
    """
    return any(name in tool_name for name in names)


# Maximum documents extracted per tool call to avoid bloating the state.
_MAX_DOCS_PER_CALL = 5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_mcp_documents(messages: List[ChatMessage]) -> List[Document]:
    """Return Documents parsed from all MCP tool-result messages.

    Performs a two-pass scan:
    1. Collect the Atlassian instance URL (needed for Jira/Confluence browse links).
    2. Parse each tool result into Documents.

    Documents are deduplicated by ``source`` URL.  At most ``_MAX_DOCS_PER_CALL``
    documents are extracted per individual tool call.
    """
    atlassian_instance_url = _find_atlassian_instance_url(messages)

    seen_sources: set[str] = set()
    documents: list[Document] = []

    for message in messages:
        if message.role != ChatRole.TOOL:
            continue
        for tcr in message.tool_call_results or []:
            if tcr.error:
                continue
            tool_name: str = (tcr.origin.tool_name if tcr.origin else "") or ""
            raw = _extract_text(tcr.result)
            if not raw:
                continue
            data = _parse_json(raw)
            if data is None:
                continue
            try:
                docs = _dispatch(tool_name, data, atlassian_instance_url)
            except Exception:
                logger.debug(
                    "Failed to parse MCP result for tool '%s'", tool_name, exc_info=True
                )
                continue
            for doc in docs:
                source = doc.meta.get("source", "")
                if source and source in seen_sources:
                    continue
                if source:
                    seen_sources.add(source)
                documents.append(doc)

    return documents


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_atlassian_instance_url(messages: List[ChatMessage]) -> str:
    """Scan messages for a getAccessibleAtlassianResources result and return
    the first instance URL found (e.g. ``https://myorg.atlassian.net``)."""
    for message in messages:
        if message.role != ChatRole.TOOL:
            continue
        for tcr in message.tool_call_results or []:
            if tcr.error:
                continue
            tool_name = (tcr.origin.tool_name if tcr.origin else "") or ""
            if not _matches_any(tool_name, _ATLASSIAN_RESOURCES_TOOLS):
                continue
            raw = _extract_text(tcr.result)
            if not raw:
                continue
            data = _parse_json(raw)
            if not isinstance(data, list):
                continue
            for entry in data:
                url = entry.get("url", "")
                if url:
                    return url.rstrip("/")
    return ""


def _extract_text(result: object) -> str:
    """Normalise a ``ToolCallResult.result`` value to a plain string."""
    if isinstance(result, str):
        return result
    # Sequence[TextContent | ImageContent]
    parts: list[str] = []
    try:
        for item in result:  # type: ignore[union-attr]
            if isinstance(item, TextContent):
                parts.append(item.text)
            elif isinstance(item, str):
                parts.append(item)
    except TypeError:
        return ""
    return "\n".join(parts)


def _parse_json(text: str) -> dict | list | None:
    """Parse a JSON string, unwrapping the MCP protocol envelope if present.

    The MCP wire format wraps payloads as::

        {"content": [{"type": "text", "text": "<inner-json>"}], ...}

    This function returns the *inner* parsed value so callers always deal with
    the actual data object.
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    # MCP envelope detection
    if isinstance(parsed, dict) and "content" in parsed:
        for item in parsed.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (json.JSONDecodeError, KeyError):
                    return None

    return parsed


def _dispatch(
    tool_name: str, data: dict | list, atlassian_instance_url: str
) -> list[Document]:
    if _matches_any(tool_name, _GITHUB_REPO_TOOLS):
        return _parse_github_repos(data)
    if _matches_any(tool_name, _JIRA_TOOLS):
        return _parse_jira_issues(data, atlassian_instance_url)
    if _matches_any(tool_name, _CONFLUENCE_TOOLS):
        return _parse_confluence_pages(data, atlassian_instance_url)
    return []


# ---------------------------------------------------------------------------
# Per-source parsers
# ---------------------------------------------------------------------------


def _parse_github_repos(data: dict | list) -> list[Document]:
    if isinstance(data, list):
        items = data
    else:
        items = data.get("items", [data] if "full_name" in data else [])

    docs: list[Document] = []
    for item in items[:_MAX_DOCS_PER_CALL]:
        full_name: str = item.get("full_name", "")
        docs.append(
            Document(
                content=item.get("description") or full_name,
                meta={
                    "title": item.get("name", full_name),
                    "source": item.get("html_url", ""),
                    "type": "GITHUB",
                    "last_updated": item.get("updated_at", ""),
                    "repo_name": full_name,
                    "file_path": "",
                    "commit_hash": "",
                    "ref": item.get("default_branch", "main"),
                },
            )
        )
    return docs


def _parse_jira_issues(data: dict | list, instance_url: str) -> list[Document]:
    if isinstance(data, list):
        issues = data
    elif "key" in data:
        issues = [data]
    else:
        issues = data.get("issues", [])

    docs: list[Document] = []
    for issue in issues[:_MAX_DOCS_PER_CALL]:
        fields: dict = issue.get("fields", {}) or {}
        key: str = issue.get("key", "")
        project_key: str = (fields.get("project") or {}).get("key", "")
        summary: str = fields.get("summary", "")
        updated: str = fields.get("updated", "")

        self_url: str = issue.get("self", "")
        if instance_url and key:
            browse_url = f"{instance_url}/browse/{key}"
        elif key and self_url:
            # Derive the browse URL from the REST self link when no instance URL
            # was discovered (e.g. getAccessibleAtlassianResources was not called).
            # self looks like https://myorg.atlassian.net/rest/api/2/issue/123
            parsed = urlparse(self_url)
            if parsed.scheme and parsed.netloc:
                base = f"{parsed.scheme}://{parsed.netloc}"
                browse_url = f"{base}/browse/{key}"
            else:
                browse_url = (
                    self_url  # best-effort: self_url is not a standard absolute URL
                )
        else:
            browse_url = self_url

        docs.append(
            Document(
                content=summary,
                meta={
                    "title": f"{key} - {summary}" if key else summary,
                    "source": browse_url,
                    "type": "JIRA",
                    "last_updated": updated,
                    "issue_key": key,
                    "project_key": project_key,
                },
            )
        )
    return docs


def _parse_confluence_pages(data: dict | list, instance_url: str) -> list[Document]:
    if isinstance(data, list):
        pages = data
    elif "id" in data:
        pages = [data]
    else:
        pages = data.get("results", [])

    docs: list[Document] = []
    for page in pages[:_MAX_DOCS_PER_CALL]:
        page_id: str = str(page.get("id", ""))
        title: str = page.get("title", page_id)
        space: dict = page.get("space", {}) or {}
        space_key: str = space.get("key", "")
        links: dict = page.get("_links", {}) or {}
        base: str = links.get("base", instance_url)
        webui: str = links.get("webui", "")
        source_url = f"{base}{webui}" if base and webui else ""
        version: dict = page.get("version", {}) or {}
        last_updated: str = version.get("when", "")

        docs.append(
            Document(
                content=title,
                meta={
                    "title": title,
                    "source": source_url,
                    "type": "CONFLUENCE",
                    "last_updated": last_updated,
                    "page_id": page_id,
                    "space_key": space_key,
                },
            )
        )
    return docs
