from atlassian import Jira
from haystack import Document

from src.common.models import DocumentSourceType, JiraMetadata
from src.core.atlassian import convert_to_markdown
from src.core.link_extractor import LinkExtractor


class JiraLoader:
    def __init__(self, url, username, api_key, projects):
        self.url = url
        self.username = username
        self.api_key = api_key
        self.projects = projects
        self.client = Jira(
            url=self.url, username=self.username, password=self.api_key, cloud=True
        )

    async def load(self):
        all_issues = []
        for project in self.projects:
            # Request issue links field along with other fields
            issues = self.client.jql(
                f"project = {project}",
                fields="summary,description,updated,comment,issuelinks",
            )
            all_issues.extend(issues["issues"])

        documents = []
        for issue in all_issues:
            content = issue["fields"]["description"] or ""
            if (
                hasattr(issue["fields"], "comment")
                and issue["fields"]["comment"]["comments"]
            ):
                comments = "\n".join(
                    [
                        comment["body"]
                        for comment in issue["fields"]["comment"]["comments"]
                    ]
                )
                content += "\n\nComments:\n" + comments

            # Extract links from Jira API issuelinks field
            links = self._extract_links_from_issue_api(issue)

            # Get remote links (Confluence, external URLs, etc.) from Jira API
            remote_links = self._get_remote_links(issue["key"])
            links["confluence_pages"].extend(remote_links.get("confluence_pages", []))
            links["external_urls"].extend(remote_links.get("external_urls", []))

            # Also parse content for GitHub references (not captured by Jira API)
            parsed_links = LinkExtractor.extract_links_for_jira(
                content=content, current_issue_key=issue["key"], jira_url=self.url
            )

            # Add parsed GitHub issues
            links["github_issues"] = parsed_links.get("github_issues", [])

            metadata = JiraMetadata(
                source=f"{self.url}/browse/{issue['key']}",
                type=DocumentSourceType.JIRA,
                last_updated=issue["fields"]["updated"],
                issue_key=issue["key"],
                project_key=project,
                title=issue["fields"]["summary"],
                links=links,
            )
            documents.append(
                Document(
                    content=convert_to_markdown(content), meta=metadata.model_dump()
                )
            )
        return documents

    def _extract_links_from_issue_api(self, issue: dict) -> dict:
        """
        Extract Jira issue links from the Jira API issuelinks field.

        Args:
            issue: Issue dict from Jira API

        Returns:
            Dict with 'jira_issues' list
        """
        jira_issues = []
        issue_links = issue.get("fields", {}).get("issuelinks", [])

        for link in issue_links:
            # Links can be inward or outward
            if "inwardIssue" in link:
                linked_issue = link["inwardIssue"]
                jira_issues.append(linked_issue.get("key"))
            elif "outwardIssue" in link:
                linked_issue = link["outwardIssue"]
                jira_issues.append(linked_issue.get("key"))

        return {
            "jira_issues": list(set(jira_issues)),  # Deduplicate
            "confluence_pages": [],
            "github_issues": [],
            "external_urls": [],
        }

    def _get_remote_links(self, issue_key: str) -> dict:
        """
        Get remote links (Confluence pages, external URLs) from Jira API.

        Args:
            issue_key: Jira issue key

        Returns:
            Dict with 'confluence_pages' and 'external_urls'
        """
        try:
            # Get remote issue links from Jira API
            remote_links = self.client.get_issue_remote_links(issue_key)

            confluence_pages = []
            external_urls = []

            for link in remote_links:
                url = link.get("object", {}).get("url", "")

                # Check if it's a Confluence link
                confluence_match = LinkExtractor.extract_confluence_pages(url)
                if confluence_match:
                    confluence_pages.extend(confluence_match)
                elif url:
                    external_urls.append(url)

            return {
                "confluence_pages": confluence_pages,
                "external_urls": external_urls,
            }
        except Exception as e:
            # If remote links API fails, return empty
            print(f"Warning: Failed to get remote links for {issue_key}: {e}")
            return {"confluence_pages": [], "external_urls": []}
