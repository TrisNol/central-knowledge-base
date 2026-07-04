from datetime import datetime
from typing import Any

from atlassian import Confluence
from haystack import Document

from src.common.models import ConfluenceMetadata, DocumentSourceType
from src.core.atlassian import convert_to_markdown
from src.core.link_extractor import LinkExtractor


def map_to_confluence_doc(doc: Document) -> Document:
    meta: ConfluenceMetadata = ConfluenceMetadata(
        source=doc.meta.get("source"),
        title=doc.meta.get("title"),
        type=DocumentSourceType.CONFLUENCE,
        last_updated=normalize_when(doc.meta.get("when")),
        page_id=doc.meta.get("id"),
        space_key=doc.meta.get("source").split("/")[5],
        links=doc.meta.get("links"),
    )
    return Document(content=doc.content, meta=meta.model_dump())


def normalize_when(when: Any) -> str:
    """Normalize various `when` inputs into an ISO-8601 string or empty string.

    Accepts strings (ISO or other), datetime objects, and numeric timestamps.
    Returns a string suitable for `ConfluenceMetadata.last_updated` which
    expects a `str`.
    """
    if when is None:
        return ""

    # Already a string: try to coerce/normalize ISO formats, otherwise return as-is
    if isinstance(when, str):
        when_str = when.strip()
        if when_str == "":
            return ""
        try:
            # Handle trailing Z by converting to +00:00 for fromisoformat
            if when_str.endswith("Z"):
                return datetime.fromisoformat(
                    when_str.replace("Z", "+00:00")
                ).isoformat()
            return datetime.fromisoformat(when_str).isoformat()
        except Exception:
            # Not ISO-parseable — return the original trimmed string
            return when_str

    # datetime -> ISO
    if isinstance(when, datetime):
        return when.isoformat()

    # numeric timestamp (seconds) -> ISO
    if isinstance(when, (int, float)):
        try:
            return datetime.fromtimestamp(when).isoformat()
        except Exception:
            return str(when)

    # Fallback: convert to string
    try:
        return str(when)
    except Exception:
        return ""


class ConfluenceLoader:
    def __init__(
        self,
        url: str,
        username: str,
        api_key: str,
        spaces: list[str],
        include_attachments: bool = False,
    ):
        self.confluence = Confluence(url=url, username=username, password=api_key)
        self.spaces = spaces
        self.include_attachments = include_attachments

    async def load(self) -> list[Document]:
        documents = []
        for space_key in self.spaces:
            documents.extend(await self._load_space(space_key))
        return documents

    async def _load_space(self, space_key: str) -> list[Document]:
        documents = []

        # The Confluence API enforces a hard limit (commonly 100) on page
        # results per request. Use `get_all_pages_from_space` with start/limit
        # pagination to retrieve all pages.
        start = 0
        limit = 100
        fetched = 0
        while True:
            # request pages; expand body.storage so we can get the page HTML
            results = self.confluence.get_all_pages_from_space(
                space_key, start=start, limit=limit, expand="body.storage"
            )

            page_count = len(results or [])
            fetched += page_count
            print(f"Fetched {page_count} pages (start={start}) from space {space_key}")

            for page in results:
                # `get_all_pages_from_space` returns page objects directly
                content_id = page.get("id")
                if not content_id:
                    continue
                title = page.get("title", "")

                # body.storage is included due to expand param
                body_storage = page.get("body", {}).get("storage", {}).get("value", "")
                page_content = f"<h1>{title}</h1>\n" + body_storage

                # The get_all_pages_from_space response does not include lastModified
                # consistently; fall back to the page 'version' or None
                when = normalize_when(page.get("version", {}).get("when"))

                # Extract links from page content
                links = LinkExtractor.extract_links_for_confluence(
                    content=page_content,
                    current_page_id=content_id,
                    confluence_url=self.confluence.url,
                )

                metadata = {
                    "source": f"{self.confluence.url}/spaces/{space_key}/pages/{content_id}",
                    "when": when,
                    "id": content_id,
                    "title": title,
                    "links": links,
                }

                document = Document(
                    content=convert_to_markdown(page_content), meta=metadata
                )
                documents.append(map_to_confluence_doc(document))

                if self.include_attachments:
                    attachments = self.confluence.get_attachments(content_id)
                    for attachment in attachments.get("results", []):
                        attachment_content = self.confluence.get_attachment_data(
                            attachment["id"]
                        )
                        attachment_metadata = {
                            "source": f"{self.confluence.url}/spaces/{space_key}/pages/{content_id}/attachments/{attachment['id']}",
                            "when": normalize_when(
                                attachment.get("version", {}).get("when")
                            ),
                            "id": attachment["id"],
                        }
                        attachment_document = Document(
                            content=attachment_content.decode("utf-8", errors="ignore"),
                            meta=attachment_metadata,
                        )
                        documents.append(map_to_confluence_doc(attachment_document))

            # If fewer than limit were returned, we've reached the end
            if page_count < limit:
                break

            # otherwise increment start to fetch the next page of results
            start += limit

        print(f"Total fetched pages from space {space_key}: {fetched}")
        return documents
