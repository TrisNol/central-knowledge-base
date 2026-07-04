"""Component for managing relationships between documents in Neo4j."""

from typing import Any, Dict, List

from haystack import Document
from neo4j import GraphDatabase


class RelationshipManager:
    """Manages relationships between documents in Neo4j graph database."""

    def __init__(
        self,
        neo4j_url: str,
        neo4j_username: str,
        neo4j_password: str,
        neo4j_database: str = "neo4j",
    ):
        """
        Initialize the relationship manager.

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

    def create_relationships(self, documents: List[Document]) -> Dict[str, int]:
        """
        Create relationships between documents based on extracted links.

        Args:
            documents: List of documents with metadata containing links

        Returns:
            Dict with statistics about created relationships
        """
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )

        stats = {
            "jira_to_jira": 0,
            "jira_to_confluence": 0,
            "confluence_to_jira": 0,
            "confluence_to_confluence": 0,
            "github_to_jira": 0,
            "github_to_confluence": 0,
            "github_to_github": 0,
        }

        print(f"Creating relationships for {len(documents)} documents...")

        try:
            with driver.session(database=self.neo4j_database) as session:
                for doc in documents:
                    meta = doc.meta
                    links = meta.get("links", {})

                    if not links:
                        continue

                    doc_type = meta.get("type", "")
                    doc_id = self._get_doc_id(meta)
                    print(f"Document {doc_type}/{doc_id} has links: {links}")

                    # Create relationships based on document type
                    if doc_type == "JIRA":
                        stats["jira_to_jira"] += self._create_jira_relationships(
                            session, meta, links
                        )
                        stats["jira_to_confluence"] += (
                            self._create_jira_to_confluence_relationships(
                                session, meta, links
                            )
                        )
                    elif doc_type == "CONFLUENCE":
                        stats["confluence_to_jira"] += (
                            self._create_confluence_to_jira_relationships(
                                session, meta, links
                            )
                        )
                        stats["confluence_to_confluence"] += (
                            self._create_confluence_relationships(session, meta, links)
                        )
                    elif doc_type == "GITHUB":
                        stats["github_to_jira"] += (
                            self._create_github_to_jira_relationships(
                                session, meta, links
                            )
                        )
                        stats["github_to_confluence"] += (
                            self._create_github_to_confluence_relationships(
                                session, meta, links
                            )
                        )
                        stats["github_to_github"] += self._create_github_relationships(
                            session, meta, links
                        )
        finally:
            driver.close()

        return stats

    def _get_doc_id(self, meta: Dict[str, Any]) -> str:
        """Generate document ID from metadata (same logic as DocumentChunkWriter)."""
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
            return "unknown"

    def _create_jira_relationships(
        self, session, source_meta: Dict[str, Any], links: Dict[str, Any]
    ) -> int:
        """Create JIRA -> JIRA relationships."""
        count = 0
        source_issue_key = source_meta.get("issue_key")
        source_id = f"jira:{source_issue_key}"

        for target_issue_key in links.get("jira_issues", []):
            target_id = f"jira:{target_issue_key}"
            print(f"  Creating JIRA->JIRA: {source_id} -> {target_id}")
            result = session.run(
                """
                MATCH (source:Document {id: $source_id})
                WITH source LIMIT 1
                MATCH (target:Document {id: $target_id})
                WITH source, target LIMIT 1
                MERGE (source)-[r:REFERENCES]->(target)
                RETURN count(r) as created
            """,
                source_id=source_id,
                target_id=target_id,
            )

            record = result.single()
            if record and record["created"] > 0:
                count += 1

        return count

    def _create_jira_to_confluence_relationships(
        self, session, source_meta: Dict[str, Any], links: Dict[str, Any]
    ) -> int:
        """Create JIRA -> Confluence relationships."""
        count = 0
        source_issue_key = source_meta.get("issue_key")
        source_id = f"jira:{source_issue_key}"

        for page_ref in links.get("confluence_pages", []):
            page_id = page_ref.get("page_id")
            target_id = f"confluence:{page_id}"
            result = session.run(
                """
                MATCH (source:Document {id: $source_id})
                WITH source LIMIT 1
                MATCH (target:Document {id: $target_id})
                WITH source, target LIMIT 1
                MERGE (source)-[r:REFERENCES]->(target)
                RETURN count(r) as created
            """,
                source_id=source_id,
                target_id=target_id,
            )

            record = result.single()
            if record and record["created"] > 0:
                count += 1

        return count

    def _create_confluence_to_jira_relationships(
        self, session, source_meta: Dict[str, Any], links: Dict[str, Any]
    ) -> int:
        """Create Confluence -> JIRA relationships."""
        count = 0
        source_page_id = source_meta.get("page_id")
        source_id = f"confluence:{source_page_id}"

        for target_issue_key in links.get("jira_issues", []):
            target_id = f"jira:{target_issue_key}"
            result = session.run(
                """
                MATCH (source:Document {id: $source_id})
                WITH source LIMIT 1
                MATCH (target:Document {id: $target_id})
                WITH source, target LIMIT 1
                MERGE (source)-[r:REFERENCES]->(target)
                RETURN count(r) as created
            """,
                source_id=source_id,
                target_id=target_id,
            )

            record = result.single()
            if record and record["created"] > 0:
                count += 1

        return count

    def _create_confluence_relationships(
        self, session, source_meta: Dict[str, Any], links: Dict[str, Any]
    ) -> int:
        """Create Confluence -> Confluence relationships."""
        count = 0
        source_page_id = source_meta.get("page_id")
        source_id = f"confluence:{source_page_id}"

        for page_ref in links.get("confluence_pages", []):
            target_page_id = page_ref.get("page_id")
            target_id = f"confluence:{target_page_id}"
            result = session.run(
                """
                MATCH (source:Document {id: $source_id})
                WITH source LIMIT 1
                MATCH (target:Document {id: $target_id})
                WITH source, target LIMIT 1
                MERGE (source)-[r:REFERENCES]->(target)
                RETURN count(r) as created
            """,
                source_id=source_id,
                target_id=target_id,
            )

            record = result.single()
            if record and record["created"] > 0:
                count += 1

        return count

    def _create_github_to_jira_relationships(
        self, session, source_meta: Dict[str, Any], links: Dict[str, Any]
    ) -> int:
        """Create GitHub -> JIRA relationships."""
        count = 0
        source_repo = source_meta.get("repo_name")
        source_file = source_meta.get("file_path")
        source_id = f"github:{source_repo}:{source_file}"

        for target_issue_key in links.get("jira_issues", []):
            target_id = f"jira:{target_issue_key}"
            result = session.run(
                """
                MATCH (source:Document {id: $source_id})
                WITH source LIMIT 1
                MATCH (target:Document {id: $target_id})
                WITH source, target LIMIT 1
                MERGE (source)-[r:REFERENCES]->(target)
                RETURN count(r) as created
            """,
                source_id=source_id,
                target_id=target_id,
            )

            record = result.single()
            if record and record["created"] > 0:
                count += 1

        return count

    def _create_github_to_confluence_relationships(
        self, session, source_meta: Dict[str, Any], links: Dict[str, Any]
    ) -> int:
        """Create GitHub -> Confluence relationships."""
        count = 0
        source_repo = source_meta.get("repo_name")
        source_file = source_meta.get("file_path")
        source_id = f"github:{source_repo}:{source_file}"

        for page_ref in links.get("confluence_pages", []):
            page_id = page_ref.get("page_id")
            target_id = f"confluence:{page_id}"
            result = session.run(
                """
                MATCH (source:Document {id: $source_id})
                WITH source LIMIT 1
                MATCH (target:Document {id: $target_id})
                WITH source, target LIMIT 1
                MERGE (source)-[r:REFERENCES]->(target)
                RETURN count(r) as created
            """,
                source_id=source_id,
                target_id=target_id,
            )

            record = result.single()
            if record and record["created"] > 0:
                count += 1

        return count

    def _create_github_relationships(
        self, session, source_meta: Dict[str, Any], links: Dict[str, Any]
    ) -> int:
        """Create GitHub -> GitHub relationships (for issue references)."""
        count = 0
        source_repo = source_meta.get("repo_name")
        source_file = source_meta.get("file_path")

        # For now, we don't have GitHub issues as documents, so this would be empty
        # This is a placeholder for future implementation when GitHub issues are indexed
        for issue_ref in links.get("github_issues", []):
            # Could create relationships to GitHub issue documents if they exist
            pass

        return count

    def clear_all_relationships(self):
        """Remove all REFERENCES relationships from the graph."""
        driver = GraphDatabase.driver(
            self.neo4j_url, auth=(self.neo4j_username, self.neo4j_password)
        )

        try:
            with driver.session(database=self.neo4j_database) as session:
                result = session.run(
                    """
                    MATCH ()-[r:REFERENCES]->()
                    DELETE r
                    RETURN count(r) as deleted
                """
                )
                record = result.single()
                return record["deleted"] if record else 0
        finally:
            driver.close()
