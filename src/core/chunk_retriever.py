"""Custom retriever for querying Chunk nodes and returning Document context."""

from typing import Any, Dict, List, Optional

from haystack import Document, component, default_from_dict, default_to_dict
from neo4j import GraphDatabase


@component
class ChunkRetriever:
    """
    Retrieves relevant chunks from Neo4j based on embedding similarity,
    and returns Document nodes with context from the matching chunks.
    """

    def __init__(
        self,
        neo4j_url: str,
        neo4j_username: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
        index_name: str = "chunk_embeddings",
        top_k: int = 5,
    ):
        """
        Initialize the chunk retriever.

        Args:
            neo4j_url: URL of the Neo4j instance
            neo4j_username: Neo4j username
            neo4j_password: Neo4j password
            neo4j_database: Neo4j database name
            index_name: Name of the vector index on Chunk nodes
            top_k: Number of top results to retrieve
        """
        self.neo4j_url = neo4j_url
        self.neo4j_username = neo4j_username
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database
        self.index_name = index_name
        self.top_k = top_k

    @component.output_types(documents=List[Document])
    def run(
        self,
        query_embedding: List[float],
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
    ) -> Dict[str, List[Document]]:
        """
        Query chunk embeddings and return parent documents with chunk content.

        Args:
            query_embedding: Embedding vector for the query
            filters: Optional filters (e.g., {"type": ["JIRA", "CONFLUENCE"]})
            top_k: Override default top_k

        Returns:
            Dict with "documents" key containing list of Document objects
        """
        k = top_k if top_k is not None else self.top_k
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )

        try:
            with driver.session(database=self.neo4j_database) as session:
                # Build Cypher query
                query = """
                CALL db.index.vector.queryNodes($index, $top_k, $query_embedding)
                YIELD node as chunk, score
                MATCH (chunk:Chunk)-[:PART_OF]->(doc:Document)
                """

                parameters = {
                    "index": self.index_name,
                    "top_k": k,
                    "query_embedding": query_embedding,
                }

                # Apply filters if provided
                if filters:
                    if "type" in filters:
                        query += "WHERE doc.type IN $types\n"
                        parameters["types"] = [t.upper() for t in filters["type"]]

                query += """
                RETURN doc, chunk.content as content, score
                ORDER BY score DESC
                LIMIT $top_k
                """

                result = session.run(query, parameters)

                # Convert Neo4j results to Haystack Documents
                documents = []
                for record in result:
                    doc_node = record["doc"]
                    chunk_content = record["content"]
                    score = record["score"]

                    # Build metadata from document node
                    metadata = dict(doc_node)
                    metadata["score"] = score

                    # Create Haystack Document with chunk content but document metadata
                    documents.append(
                        Document(
                            content=chunk_content,
                            meta=metadata,
                        )
                    )

                return {"documents": documents}

        finally:
            driver.close()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return default_to_dict(
            self,
            neo4j_url=self.neo4j_url,
            neo4j_username=self.neo4j_username,
            neo4j_password=self.neo4j_password,
            neo4j_database=self.neo4j_database,
            index_name=self.index_name,
            top_k=self.top_k,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkRetriever":
        """Deserialize from dictionary."""
        return default_from_dict(cls, data)
