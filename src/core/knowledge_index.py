from typing import Optional

from haystack import Document, Pipeline
from haystack.components.preprocessors import DocumentSplitter

from src.core.document_chunk_writer import DocumentChunkWriter
from src.core.relationship_manager import RelationshipManager


class KrakenDocumentSplitter(DocumentSplitter):
    def split(self, document: Document):
        meta_type = document.meta.get("type", "").upper()

        if meta_type == "CONFLUENCE":
            # Split at chapters with an overlap
            return self.split_markdown_chapters_with_overlap(document)
        elif meta_type == "JIRA":
            # Split at chapters without overlap
            return self.split_markdown_chapters(document)
        elif meta_type == "GITHUB":
            # Only split if really necessary
            return self.split_if_necessary(document)
        else:
            # Default splitting behavior
            return super().split(document)

    def split_markdown_chapters_with_overlap(self, document: Document):
        # Custom logic to split markdown chapters with overlap
        chapters = document.content.split("\n# ")  # Split by markdown chapter headers
        overlap = 1  # Example: Overlap of 1 chapter
        split_documents = []

        for i in range(len(chapters)):
            start = max(0, i - overlap)
            end = i + 1
            content = "\n# ".join(chapters[start:end])
            split_documents.append(Document(content=content, meta=document.meta))

        return split_documents

    def split_markdown_chapters(self, document: Document):
        # Custom logic to split markdown chapters without overlap
        chapters = document.content.split("\n# ")  # Split by markdown chapter headers
        split_documents = [
            Document(content=f"# {chapter}" if idx > 0 else chapter, meta=document.meta)
            for idx, chapter in enumerate(chapters)
        ]
        return split_documents

    def split_if_necessary(self, document: Document):
        # Custom logic to split only if necessary
        max_length = 1000  # Example threshold
        if len(document.content) > max_length:
            midpoint = len(document.content) // 2
            return [
                Document(content=document.content[:midpoint], meta=document.meta),
                Document(content=document.content[midpoint:], meta=document.meta),
            ]
        return [document]


class KnowledgeIndex:
    indexing_pipeline: Pipeline = None
    relationship_manager: Optional[RelationshipManager] = None
    chunk_writer: Optional[DocumentChunkWriter] = None

    def __init__(
        self,
        document_embedder,
        relationship_manager: Optional[RelationshipManager] = None,
        chunk_writer: Optional[DocumentChunkWriter] = None,
    ):
        splitter = KrakenDocumentSplitter()

        # Construct pipeline
        self.indexing_pipeline = Pipeline()
        self.indexing_pipeline.add_component("splitter", splitter)
        self.indexing_pipeline.add_component("embedder", document_embedder)

        # Use custom chunk writer if provided
        if chunk_writer:
            self.chunk_writer = chunk_writer
            self.indexing_pipeline.add_component("writer", chunk_writer)

        self.indexing_pipeline.connect("splitter", "embedder")
        self.indexing_pipeline.connect("embedder", "writer")

        # Store relationship manager for creating document links
        self.relationship_manager = relationship_manager

    def create_index(self, documents: list[Document]):
        # Filter out documents with less than 50 characters
        documents = [
            d
            for d in documents
            if getattr(d, "content", None) and len(str(d.content)) >= 50
        ]
        if not documents:
            return

        # Index documents FIRST (creates Document + Chunk nodes in Neo4j)
        self.indexing_pipeline.run({"documents": documents})

        # Create relationships AFTER indexing (now MATCH queries can find the Document nodes)
        if self.relationship_manager:
            try:
                stats = self.relationship_manager.create_relationships(documents)
                print(f"Created relationships: {stats}")
            except Exception as e:
                print(f"Warning: Failed to create relationships: {e}")

    def _remove_links_from_db(self):
        """Remove links property from all Document nodes in Neo4j."""
        if not self.chunk_writer:
            return

        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                self.chunk_writer.neo4j_url,
                auth=(
                    self.chunk_writer.neo4j_username,
                    self.chunk_writer.neo4j_password,
                ),
            )

            with driver.session(database=self.chunk_writer.neo4j_database) as session:
                result = session.run(
                    """
                    MATCH (d:Document)
                    WHERE d.links IS NOT NULL
                    REMOVE d.links
                    RETURN count(d) as cleaned
                """
                )
                record = result.single()
                if record:
                    print(f"Cleaned links from {record['cleaned']} document nodes")

            driver.close()
        except Exception as e:
            print(f"Warning: Failed to clean links from database: {e}")

    def get_index_stats(self):
        """Get statistics about indexed documents and chunks."""
        if not self.chunk_writer:
            return {}

        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                self.chunk_writer.neo4j_url,
                auth=(
                    self.chunk_writer.neo4j_username,
                    self.chunk_writer.neo4j_password,
                ),
            )

            with driver.session(database=self.chunk_writer.neo4j_database) as session:
                result = session.run(
                    """
                    MATCH (d:Document)
                    OPTIONAL MATCH (d)<-[:PART_OF]-(c:Chunk)
                    RETURN count(DISTINCT d) as documents, count(c) as chunks
                """
                )
                record = result.single()
                if record:
                    return {
                        "documents": record["documents"],
                        "chunks": record["chunks"],
                    }

            driver.close()
        except Exception as e:
            print(f"Warning: Failed to get index stats: {e}")
            return {}

    def clear_index(self):
        """Clear all Document and Chunk nodes from Neo4j."""
        if not self.chunk_writer:
            return

        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                self.chunk_writer.neo4j_url,
                auth=(
                    self.chunk_writer.neo4j_username,
                    self.chunk_writer.neo4j_password,
                ),
            )

            with driver.session(database=self.chunk_writer.neo4j_database) as session:
                session.run(
                    """
                    MATCH (c:Chunk)
                    DETACH DELETE c
                """
                )
                session.run(
                    """
                    MATCH (d:Document)
                    DETACH DELETE d
                """
                )

            driver.close()
        except Exception as e:
            print(f"Warning: Failed to clear index: {e}")
