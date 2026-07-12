def _docs_to_summary(documents: list) -> str:
    """Convert a list of Haystack Documents to a concise summary for the LLM."""
    if not documents:
        return "No documents found."
    lines = [f"Found {len(documents)} document(s):"]
    for i, doc in enumerate(documents, 1):
        meta = doc.meta if hasattr(doc, "meta") else {}
        doc_type = meta.get("type", "UNKNOWN")
        title = meta.get(
            "title", meta.get("issue_key", meta.get("file_path", "Untitled"))
        )
        source = meta.get("source", "")
        snippet = (doc.content or "")[:200].replace("\n", " ")
        lines.append(f"  [{i}] ({doc_type}) {title} — {snippet}...")
        if source:
            lines.append(f"      Source: {source}")
    lines.append(
        "\nYou can now call fetch_neighbors_tool to expand context, filter_docs_tool to narrow results, or answer the question based on these documents."
    )
    return "\n".join(lines)


def _mcp_source_registered_summary(documents: list) -> str:
    """Confirm a single MCP source registration to the LLM."""
    if not documents:
        return "Source registration failed — no document was created."
    doc = documents[0]
    title = doc.meta.get("title", "Untitled")
    source = doc.meta.get("source", "")
    source_type = doc.meta.get("type", "UNKNOWN")
    return (
        f"Source registered: '{title}' (type={source_type}, url={source}). "
        "Call register_mcp_sources_tool again for each additional source you used, "
        "then give your final answer."
    )
