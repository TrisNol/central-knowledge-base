# Development

## Development workflow

### Python formatting and linting

This repository uses Ruff as the single source of truth for Python linting,
import ordering, and formatting.

1. Install hooks:
    ```
	poetry run pre-commit install
    ```

2. Run checks across the repository:
    ```
	poetry run pre-commit run --all-files
    ```

3. In VS Code, Python files are formatted on save with Ruff and use Ruff code
	 actions for auto-fixes and import organization.

### Style notes for merge-friendly diffs

- Keep trailing commas in multiline collections and call signatures so formatting
	remains stable when adding new items.
- Imports may be grouped in `from ... import (...)` form; keep trailing commas in
	multiline imports for stable diffs when extending lists.
- Function parameters are split one-per-line when line wrapping is required by
	formatter rules.

## Agentic software engineering
