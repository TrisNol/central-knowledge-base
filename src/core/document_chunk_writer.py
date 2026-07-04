"""Custom document writer that creates separate Document and Chunk nodes in Neo4j."""

import hashlib
from typing import List

from haystack import Document, component, default_from_dict, default_to_dict
from haystack.document_stores.types import DuplicatePolicy
from neo4j import GraphDatabase


@component
class DocumentChunkWriter:
    """
    Writes documents to Neo4j with a two-tier structure:
    - Document nodes: Hold metadata and relationships
    - Chunk nodes: Hold content and embeddings, reference parent document
    """

    def __init__(
        self,
        neo4j_url: str,
        neo4j_username: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
        embedding_dim: int = 768,
        policy: DuplicatePolicy = DuplicatePolicy.OVERWRITE,
    ):
        self.neo4j_url = neo4j_url
        self.neo4j_username = neo4j_username
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database
        self.embedding_dim = embedding_dim
        self.policy = policy

        # Ensure vector index exists on Chunk nodes
        self._ensure_index()

    def _ensure_index(self):
        """Create vector index on Chunk nodes if it doesn't exist."""
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )

        try:
            with driver.session(database=self.neo4j_database) as session:
                # Check if index exists
                result = session.run(
                    """
                    SHOW INDEXES
                    YIELD name, type
                    WHERE name = 'chunk_embeddings' AND type = 'VECTOR'
                    RETURN count(*) as count
                """
                )
                record = result.single()

                if record and record["count"] == 0:
                    # Create vector index
                    session.run(
                        f"""
                        CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
                        FOR (c:Chunk)
                        ON c.embedding
                        OPTIONS {{
                            indexConfig: {{
                                `vector.dimensions`: {self.embedding_dim},
                                `vector.similarity_function`: 'cosine'
                            }}
                        }}
                    """
                    )
                    print("Created vector index 'chunk_embeddings' on Chunk nodes")
        except Exception as e:
            print(f"Warning: Could not ensure vector index: {e}")
        finally:
            driver.close()

    @component.output_types(documents_written=int)
    def run(self, documents: List[Document]) -> dict:
        """
        Write documents to Neo4j as Document + Chunk nodes.

        Args:
            documents: List of document chunks to write

        Returns:
            Dict with number of documents written
        """
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )

        written_count = 0

        try:
            with driver.session(database=self.neo4j_database) as session:
                # Group chunks by their parent document
                doc_groups = self._group_by_document(documents)

                for doc_id, chunks in doc_groups.items():
                    # Get metadata from first chunk (all chunks share same metadata)
                    first_chunk = chunks[0]
                    meta = first_chunk.meta

                    # Create or update Document node (without links)
                    clean_meta = {k: v for k, v in meta.items() if k != "links"}
                    self._create_document_node(session, doc_id, clean_meta)

                    # Create Chunk nodes and link to Document with ordering
                    for chunk_index, chunk in enumerate(chunks):
                        self._create_chunk_node(session, doc_id, chunk, chunk_index)

                    written_count += len(chunks)

        finally:
            driver.close()

        return {"documents_written": written_count}

    def _group_by_document(self, documents: List[Document]) -> dict:
        """Group chunks by their parent document ID."""
        groups = {}

        for doc in documents:
            # Generate document ID based on unique identifiers in metadata
            doc_id = self._generate_doc_id(doc.meta)

            if doc_id not in groups:
                groups[doc_id] = []
            groups[doc_id].append(doc)

        return groups

    def _generate_doc_id(self, meta: dict) -> str:
        """Generate a unique document ID from metadata."""
        doc_type = meta.get("type", "")

        if doc_type == "JIRA":
            return f"jira:{meta.get('issue_key', '')}"
        elif doc_type == "CONFLUENCE":
            return f"confluence:{meta.get('page_id', '')}"
        elif doc_type == "GITHUB":
            repo = meta.get("repo_name", "")
            file_path = meta.get("file_path", "")
            return f"github:{repo}:{file_path}"
        else:
            # Fallback: hash the source
            source = meta.get("source", "")
            return hashlib.md5(source.encode()).hexdigest()

    def _create_document_node(self, session, doc_id: str, meta: dict):
        """Create or update a Document node."""
        # Remove embedding if present
        meta_without_embedding = {k: v for k, v in meta.items() if k != "embedding"}

        session.run(
            """
            MERGE (d:Document {id: $doc_id})
            SET d += $meta
            RETURN d
        """,
            doc_id=doc_id,
            meta=meta_without_embedding,
        )

    def _create_chunk_node(
        self, session, doc_id: str, chunk: Document, chunk_index: int
    ):
        """Create a Chunk node and link it to its parent Document."""
        # Generate chunk ID
        chunk_id = hashlib.md5(
            f"{doc_id}:{chunk_index}:{chunk.content[:100]}".encode()
        ).hexdigest()

        # Extract embedding if present
        embedding = chunk.meta.get("embedding", chunk.embedding)

        # Create chunk properties (only content and chunk_index)
        chunk_props = {
            "id": chunk_id,
            "content": chunk.content,
            "chunk_index": chunk_index,
        }

        if embedding:
            session.run(
                """
                MERGE (c:Chunk {id: $chunk_id})
                SET c += $props
                SET c.embedding = $embedding
                WITH c
                MATCH (d:Document {id: $doc_id})
                MERGE (c)-[:PART_OF {chunk_index: $chunk_index}]->(d)
                RETURN c
            """,
                chunk_id=chunk_id,
                props=chunk_props,
                embedding=embedding,
                doc_id=doc_id,
                chunk_index=chunk_index,
            )
        else:
            session.run(
                """
                MERGE (c:Chunk {id: $chunk_id})
                SET c += $props
                WITH c
                MATCH (d:Document {id: $doc_id})
                MERGE (c)-[:PART_OF {chunk_index: $chunk_index}]->(d)
                RETURN c
            """,
                chunk_id=chunk_id,
                props=chunk_props,
                doc_id=doc_id,
                chunk_index=chunk_index,
            )

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentChunkWriter":
        """Deserialize from dict."""
        return default_from_dict(cls, data)

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return default_to_dict(
            self,
            neo4j_url=self.neo4j_url,
            neo4j_username=self.neo4j_username,
            neo4j_password=self.neo4j_password,
            neo4j_database=self.neo4j_database,
            embedding_dim=self.embedding_dim,
            policy=self.policy,
        )
