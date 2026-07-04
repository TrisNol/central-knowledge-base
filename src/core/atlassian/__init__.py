from markdownify import markdownify as md


def convert_to_markdown(content: str) -> str:
    return md(content)
