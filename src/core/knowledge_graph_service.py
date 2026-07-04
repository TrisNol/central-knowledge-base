from typing import List, Tuple

from neo4j import GraphDatabase

from src.common.models import (
    ConfluenceMetadata,
    DocumentSourceType,
    GitHubMetadata,
    GraphEdge,
    GraphNode,
    JiraMetadata,
)


class KnowledgeGraphService:
    """Service for fetching and processing knowledge graph data from Neo4j."""

    def __init__(
        self,
        neo4j_url: str,
        neo4j_username: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
    ):
        """
        Initialize the knowledge graph service.

        Args:
            neo4j_url: URL of the Neo4j instance
            neo4j_username: Neo4j username
            neo4j_password: Neo4j password
            neo4j_database: Neo4j database name (default: "neo4j")
        """
        self.neo4j_url = neo4j_url
        self.neo4j_username = neo4j_username
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database

    def fetch_graph(
        self, limit: int = 100, relationship_type: str = "REFERENCES"
    ) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """
        Fetch nodes and edges from Neo4j.

        Args:
            limit: Maximum number of nodes to fetch
            relationship_type: Type of relationship to fetch (default: REFERENCES)

        Returns:
            Tuple of (nodes, edges) where nodes is a list of GraphNode and edges is a list of GraphEdge
        """
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )

        nodes_dict = {}
        edges = []

        try:
            with driver.session(database=self.neo4j_database) as session:
                # Fetch document nodes
                self._fetch_document_nodes(session, nodes_dict, limit)

                # Fetch relationships and build edges
                self._fetch_relationships(session, nodes_dict, edges, relationship_type)

                print(
                    f"Fetched {len(nodes_dict)} nodes and {len(edges)} edges from Neo4j"
                )
        finally:
            driver.close()

        return list(nodes_dict.values()), edges

    def _fetch_document_nodes(self, session, nodes_dict: dict, limit: int):
        """Fetch Document nodes and add them to nodes_dict."""
        result = session.run(
            """
            MATCH (d:Document)
            RETURN d
            LIMIT $limit
        """,
            limit=limit,
        )

        for record in result:
            doc = record["d"]
            self._add_node_to_dict(nodes_dict, doc)

    def _fetch_relationships(
        self, session, nodes_dict: dict, edges: list, relationship_type: str
    ):
        """Fetch REFERENCES relationships and build edges."""
        result = session.run(
            f"""
            MATCH (source:Document)-[rel:{relationship_type}]->(target:Document)
            RETURN source, target, rel
            LIMIT 1000
        """
        )

        for record in result:
            source_doc = record["source"]
            target_doc = record["target"]
            source_id = source_doc.element_id
            target_id = target_doc.element_id

            # Ensure both nodes are in the dictionary
            self._add_node_to_dict(nodes_dict, source_doc)
            self._add_node_to_dict(nodes_dict, target_doc)

            # Add edge
            edges.append(
                GraphEdge(
                    source=source_id, target=target_id, relationship=record["rel"].type
                )
            )

    def _add_node_to_dict(self, nodes_dict: dict, doc_node):
        """Add a document node to the nodes dictionary if not already present."""
        doc_id = doc_node.element_id

        if doc_id not in nodes_dict:
            doc_metadata = dict(doc_node)
            doc_type = doc_metadata.get("type", "JIRA")
            title, metadata = self._build_node_metadata(doc_type, doc_metadata)
            url = doc_metadata.get("source", "#")

            nodes_dict[doc_id] = GraphNode(
                id=doc_id, title=title, url=url, type=doc_type, metadata=metadata
            )

    def _build_node_metadata(
        self, doc_type: str, metadata_dict: dict
    ) -> Tuple[str, JiraMetadata | ConfluenceMetadata | GitHubMetadata]:
        """
        Build title and metadata based on document type.

        Args:
            doc_type: Type of the document
            metadata_dict: Dictionary containing document metadata

        Returns:
            Tuple of (title, metadata)
        """
        if doc_type == "JIRA":
            title = metadata_dict.get("issue_key", "Jira")
            metadata = JiraMetadata(
                source=metadata_dict.get("source", ""),
                type=DocumentSourceType.JIRA,
                last_updated=metadata_dict.get("last_updated", ""),
                issue_key=metadata_dict.get("issue_key", ""),
                project_key=metadata_dict.get("project_key", ""),
                title=metadata_dict.get("title", ""),
            )
        elif doc_type == "CONFLUENCE":
            space_key = metadata_dict.get("space_key", "")
            doc_title = metadata_dict.get("title", "")
            title = (
                f"{space_key}: {doc_title}" if space_key and doc_title else "Confluence"
            )
            metadata = ConfluenceMetadata(
                source=metadata_dict.get("source", ""),
                type=DocumentSourceType.CONFLUENCE,
                last_updated=metadata_dict.get("last_updated", ""),
                page_id=metadata_dict.get("page_id", ""),
                space_key=space_key,
                title=doc_title,
            )
        elif doc_type == "GITHUB":
            repo_name = metadata_dict.get("repo_name", "")
            file_path = metadata_dict.get("file_path", "")
            title = f"{repo_name}/{file_path}" if repo_name and file_path else "GitHub"
            metadata = GitHubMetadata(
                source=metadata_dict.get("source", ""),
                type=DocumentSourceType.GITHUB,
                last_updated=metadata_dict.get("last_updated", ""),
                repo_name=repo_name,
                file_path=file_path,
                commit_hash=metadata_dict.get("commit_hash", ""),
                ref=metadata_dict.get("ref", "main"),
            )
        else:
            # Default to JIRA type if unknown
            title = "Document"
            metadata = JiraMetadata(
                source=metadata_dict.get("source", ""),
                type=DocumentSourceType.JIRA,
                last_updated=metadata_dict.get("last_updated", ""),
                issue_key="",
                project_key="",
                title=title,
            )

        return title, metadata

    def fetch_document_relationships(
        self, doc_id: str, depth: int = 1
    ) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """
        Fetch a document and its related documents up to a certain depth.

        Args:
            doc_id: Element ID of the document node
            depth: How many hops to traverse (default: 1)

        Returns:
            Tuple of (nodes, edges) for the subgraph
        """
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )

        nodes_dict = {}
        edges = []

        try:
            with driver.session(database=self.neo4j_database) as session:
                result = session.run(
                    """
                    MATCH path = (start:Document)-[:REFERENCES*1..$depth]-(related:Document)
                    WHERE elementId(start) = $doc_id
                    UNWIND relationships(path) as rel
                    WITH startNode(rel) as source, rel, endNode(rel) as target
                    RETURN source, rel, target
                """,
                    doc_id=doc_id,
                    depth=depth,
                )

                for record in result:
                    source_doc = record["source"]
                    target_doc = record["target"]

                    # Add nodes
                    self._add_node_to_dict(nodes_dict, source_doc)
                    self._add_node_to_dict(nodes_dict, target_doc)

                    # Add edge
                    edges.append(
                        GraphEdge(
                            source=source_doc.element_id,
                            target=target_doc.element_id,
                            relationship=record["rel"].type,
                        )
                    )

        finally:
            driver.close()

        return list(nodes_dict.values()), edges

    def get_relationship_stats(self) -> dict:
        """
        Get statistics about relationships in the graph.

        Returns:
            Dict with relationship statistics
        """
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )

        try:
            with driver.session(database=self.neo4j_database) as session:
                result = session.run(
                    """
                    MATCH (source:Document)-[r:REFERENCES]->(target:Document)
                    RETURN
                        source.type as source_type,
                        target.type as target_type,
                        count(r) as count
                    ORDER BY count DESC
                """
                )

                stats = {}
                for record in result:
                    key = f"{record['source_type']}_to_{record['target_type']}"
                    stats[key] = record["count"]

                return stats

        finally:
            driver.close()
