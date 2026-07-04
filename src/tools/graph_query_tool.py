import json
from typing import List

from haystack import Document, component
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.dataclasses import ChatMessage
from neo4j import GraphDatabase

EXTRACTION_SYSTEM_PROMPT = """\
You are a query analyzer for a Neo4j knowledge graph. Your job is to extract structured filters from a user's natural language question.

The graph contains Document nodes with these properties depending on their type:

**All documents:** id, type, title, source, last_updated
**JIRA documents:** issue_key (e.g. "DEV-42"), project_key (e.g. "DEV"), title
**CONFLUENCE documents:** page_id, space_key (e.g. "ENG"), title
**GITHUB documents:** repo_name (e.g. "org/repo"), file_path (e.g. "src/main.py"), commit_hash, ref

Respond ONLY with a JSON object (no markdown fencing) containing the filters to apply. Use only the keys below. Omit keys you cannot determine from the query.

{
  "type": "JIRA" | "CONFLUENCE" | "GITHUB",
  "issue_key": "exact Jira key like DEV-42",
  "project_key": "Jira project prefix like DEV",
  "space_key": "Confluence space key",
  "page_id": "Confluence page ID",
  "repo_name": "GitHub repo like org/repo",
  "file_path": "file path or partial path",
  "title": "keyword(s) to search in the title",
  "text_search": "fallback free-text search terms if no specific identifier is found"
}
"""


@component
class GraphQuery:
    """Search the knowledge graph using an LLM to extract structured filters from natural language."""

    def __init__(
        self,
        neo4j_url: str,
        neo4j_username: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
        chat_generator: OpenAIChatGenerator = None,
    ):
        self.neo4j_url = neo4j_url
        self.neo4j_username = neo4j_username
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database
        self.chat_generator = chat_generator

    @component.output_types(documents=List[Document])
    def run(self, query: str, allowed_sources: List[str] | None = None) -> dict:
        # Step 1: Use LLM to extract structured filters
        filters = self._extract_filters(query)

        # Step 2: Build and execute Cypher query from filters
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )
        try:
            with driver.session(database=self.neo4j_database) as session:
                cypher, params = self._build_cypher(
                    filters,
                    allowed_sources=allowed_sources,
                )
                result = session.run(cypher, params)

                documents = []
                for record in result:
                    doc_node = record["d"]
                    chunks = record["chunks"]
                    metadata = dict(doc_node)
                    content = (
                        "\n---\n".join(c for c in chunks if c)
                        if chunks
                        else metadata.get("title", "")
                    )
                    documents.append(Document(content=content, meta=metadata))

                return {"documents": documents}
        finally:
            driver.close()

    def _extract_filters(self, query: str) -> dict:
        """Use the chat generator to extract structured filters from the query."""
        messages = [
            ChatMessage.from_system(EXTRACTION_SYSTEM_PROMPT),
            ChatMessage.from_user(query),
        ]
        result = self.chat_generator.run(messages=messages)
        reply = result["replies"][0].text.strip()

        try:
            return json.loads(reply)
        except json.JSONDecodeError:
            # Fallback: use the raw query as a text search
            return {"text_search": query}

    @staticmethod
    def _build_cypher(
        filters: dict,
        allowed_sources: List[str] | None = None,
    ) -> tuple[str, dict]:
        """Build a Cypher MATCH query from extracted filters."""
        conditions = []
        params = {}

        if allowed_sources:
            conditions.append("d.type IN $allowed_sources")
            params["allowed_sources"] = [source.upper() for source in allowed_sources]

        # Exact-match properties
        exact_fields = [
            "type",
            "issue_key",
            "project_key",
            "space_key",
            "page_id",
            "repo_name",
        ]
        for field in exact_fields:
            if field in filters and filters[field]:
                conditions.append(f"d.{field} = ${field}")
                params[field] = filters[field]

        # CONTAINS-match properties (partial matching)
        contains_fields = ["file_path", "title"]
        for field in contains_fields:
            if field in filters and filters[field]:
                conditions.append(f"toLower(d.{field}) CONTAINS toLower(${field})")
                params[field] = filters[field]

        # Fallback text search across multiple fields
        if "text_search" in filters and filters["text_search"] and not conditions:
            conditions.append(
                "(toLower(d.title) CONTAINS toLower($text_search)"
                " OR toLower(d.issue_key) CONTAINS toLower($text_search)"
                " OR toLower(d.project_key) CONTAINS toLower($text_search)"
                " OR toLower(d.space_key) CONTAINS toLower($text_search)"
                " OR toLower(d.repo_name) CONTAINS toLower($text_search)"
                " OR toLower(d.file_path) CONTAINS toLower($text_search))"
            )
            params["text_search"] = filters["text_search"]

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        cypher = f"""
            MATCH (d:Document)
            {where_clause}
            OPTIONAL MATCH (c:Chunk)-[:PART_OF]->(d)
            WITH d, collect(c.content) AS chunks
            RETURN d, chunks
            LIMIT 10
        """
        return cypher, params
