import tempfile
from pathlib import Path
from typing import Optional

from git import Repo
from haystack import Document

from src.common.models import DocumentSourceType, GitHubMetadata
from src.core.link_extractor import LinkExtractor


class GitHubLoader:
    def __init__(
        self,
        repositories: list[str],
        ref: Optional[str] = "main",
        token: Optional[str] = None,
    ):
        self.repositories = repositories
        self.ref = ref
        self.token = token

    def clone_repository(self, repo_url: str, dest_dir: str):
        Repo.clone_from(repo_url, dest_dir, branch=self.ref)

    def get_files(
        self, base_path: Path, include_patterns: list[str], exclude_patterns: list[str]
    ) -> list[Path]:
        all_files = list(base_path.rglob("*"))
        included_files = [
            f for f in all_files if any(f.match(p) for p in include_patterns)
        ]
        excluded_files = {
            f for f in all_files if any(f.match(p) for p in exclude_patterns)
        }
        return [f for f in included_files if f not in excluded_files]

    async def load(self) -> list[Document]:
        documents = []
        include_patterns = [
            "**/*.md",
            "**/*.txt",
            "**/*.rst",
            "**/*.py",
            "**/*.java",
            "**/*.js",
            "**/*.ts",
        ]
        exclude_patterns = ["**/node_modules/**", "**/.git/**", "**/__pycache__/**"]

        for repo in self.repositories:
            repo_name = repo.split("/")[-1].replace(".git", "")
            with tempfile.TemporaryDirectory() as temp_dir:
                self.clone_repository(repo, temp_dir)
                base_path = Path(temp_dir)
                files = self.get_files(base_path, include_patterns, exclude_patterns)

                for file_path in files:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    relative_path = file_path.relative_to(base_path)

                    # Extract links from file content
                    links = LinkExtractor.extract_links_for_github(
                        content=content, current_repo=repo_name
                    )

                    repo_object = Repo(temp_dir)
                    metadata = GitHubMetadata(
                        source=repo,
                        type=DocumentSourceType.GITHUB,
                        last_updated=repo_object.git.log(
                            "-1", "--format=%ai", "--", str(file_path)
                        ).strip(),  # Last commit date for the file
                        repo_name=repo_name,
                        file_path=str(relative_path),
                        commit_hash=repo_object.head.object.hexsha,  # Latest commit hash
                        ref=self.ref or "",
                        links=links,
                    )
                    documents.append(
                        Document(content=content, meta=metadata.model_dump())
                    )

        return documents
