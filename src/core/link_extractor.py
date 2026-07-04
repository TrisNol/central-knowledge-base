"""Utility module for extracting references and links from documents."""

import re
from typing import Dict, List


class LinkExtractor:
    """Extract references and links from document content."""

    # Jira issue key pattern (e.g., PROJECT-123, JIRA-456)
    JIRA_ISSUE_PATTERN = r"\b([A-Z][A-Z0-9]+-\d+)\b"

    # Confluence URL patterns
    CONFLUENCE_URL_PATTERN = r"https?://[^/]+/(?:wiki/)?spaces/([^/]+)/pages/(\d+)"

    # GitHub issue/PR pattern (e.g., #123, owner/repo#456)
    GITHUB_ISSUE_PATTERN = r"(?:([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+))?#(\d+)"

    # Generic URL pattern
    URL_PATTERN = r'https?://[^\s<>"{}|\\^`\[\]]+'

    @staticmethod
    def extract_jira_issues(content: str, exclude_self: str = None) -> List[str]:
        """
        Extract Jira issue keys from content.

        Args:
            content: Document content to search
            exclude_self: Issue key to exclude (typically the current document's key)

        Returns:
            List of unique Jira issue keys found
        """
        matches = re.findall(LinkExtractor.JIRA_ISSUE_PATTERN, content)
        unique_issues = list(set(matches))

        if exclude_self:
            unique_issues = [issue for issue in unique_issues if issue != exclude_self]

        return unique_issues

    @staticmethod
    def extract_confluence_pages(
        content: str, exclude_self: str = None
    ) -> List[Dict[str, str]]:
        """
        Extract Confluence page references from content.

        Args:
            content: Document content to search
            exclude_self: Page ID to exclude (typically the current document's page)

        Returns:
            List of dicts with 'space_key' and 'page_id' found
        """
        matches = re.findall(LinkExtractor.CONFLUENCE_URL_PATTERN, content)
        unique_pages = []
        seen = set()

        for space_key, page_id in matches:
            if exclude_self and page_id == exclude_self:
                continue

            key = f"{space_key}:{page_id}"
            if key not in seen:
                seen.add(key)
                unique_pages.append({"space_key": space_key, "page_id": page_id})

        return unique_pages

    @staticmethod
    def extract_github_issues(
        content: str, current_repo: str = None
    ) -> List[Dict[str, str]]:
        """
        Extract GitHub issue/PR references from content.

        Args:
            content: Document content to search
            current_repo: Current repository name (owner/repo) for context

        Returns:
            List of dicts with 'repo' and 'issue_number' found
        """
        matches = re.findall(LinkExtractor.GITHUB_ISSUE_PATTERN, content)
        unique_issues = []
        seen = set()

        for owner, repo, issue_num in matches:
            # If no repo specified, use current repo context
            if not owner and current_repo:
                owner, repo = (
                    current_repo.split("/", 1)
                    if "/" in current_repo
                    else (current_repo, "")
                )

            if owner and repo:
                key = f"{owner}/{repo}#{issue_num}"
                if key not in seen:
                    seen.add(key)
                    unique_issues.append(
                        {"repo": f"{owner}/{repo}", "issue_number": issue_num}
                    )

        return unique_issues

    @staticmethod
    def extract_all_urls(content: str) -> List[str]:
        """
        Extract all URLs from content.

        Args:
            content: Document content to search

        Returns:
            List of unique URLs found
        """
        matches = re.findall(LinkExtractor.URL_PATTERN, content)
        return list(set(matches))

    @staticmethod
    def extract_links_for_jira(
        content: str, current_issue_key: str, jira_url: str
    ) -> Dict[str, List]:
        """
        Extract all relevant links from a Jira issue.

        Args:
            content: Issue content
            current_issue_key: Current issue key to exclude
            jira_url: Base Jira URL

        Returns:
            Dict with 'jira_issues', 'confluence_pages', and 'github_issues'
        """
        return {
            "jira_issues": LinkExtractor.extract_jira_issues(
                content, exclude_self=current_issue_key
            ),
            "confluence_pages": LinkExtractor.extract_confluence_pages(content),
            "github_issues": LinkExtractor.extract_github_issues(content),
            "external_urls": [
                url
                for url in LinkExtractor.extract_all_urls(content)
                if not url.startswith(jira_url)
            ],
        }

    @staticmethod
    def extract_links_for_confluence(
        content: str, current_page_id: str, confluence_url: str
    ) -> Dict[str, List]:
        """
        Extract all relevant links from a Confluence page.

        Args:
            content: Page content
            current_page_id: Current page ID to exclude
            confluence_url: Base Confluence URL

        Returns:
            Dict with 'jira_issues', 'confluence_pages', and 'github_issues'
        """
        return {
            "jira_issues": LinkExtractor.extract_jira_issues(content),
            "confluence_pages": LinkExtractor.extract_confluence_pages(
                content, exclude_self=current_page_id
            ),
            "github_issues": LinkExtractor.extract_github_issues(content),
            "external_urls": [
                url
                for url in LinkExtractor.extract_all_urls(content)
                if not url.startswith(confluence_url)
            ],
        }

    @staticmethod
    def extract_links_for_github(content: str, current_repo: str) -> Dict[str, List]:
        """
        Extract all relevant links from a GitHub file.

        Args:
            content: File content
            current_repo: Current repository name (owner/repo)

        Returns:
            Dict with 'jira_issues', 'confluence_pages', and 'github_issues'
        """
        return {
            "jira_issues": LinkExtractor.extract_jira_issues(content),
            "confluence_pages": LinkExtractor.extract_confluence_pages(content),
            "github_issues": LinkExtractor.extract_github_issues(
                content, current_repo=current_repo
            ),
            "external_urls": LinkExtractor.extract_all_urls(content),
        }
