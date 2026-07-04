from __future__ import annotations

from haystack_integrations.tools.mcp import MCPToolset, StreamableHttpServerInfo

from src.core.auth.models import OAuthProvider

_PROVIDER_ENDPOINTS = {
    OAuthProvider.GITHUB: "https://api.githubcopilot.com/mcp/",
    OAuthProvider.ATLASSIAN: "https://mcp.atlassian.com/v1/mcp",
}


def provider_endpoint(provider: OAuthProvider) -> str:
    return _PROVIDER_ENDPOINTS[provider]


def create_oauth_mcp_toolset(provider: OAuthProvider, access_token: str) -> MCPToolset:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {access_token}",
    }
    if provider == OAuthProvider.GITHUB:
        headers.update(
            {
                "X-MCP-Toolsets": "repos,issues,pull_requests,notifications,users,code_security",
                "X-MCP-Readonly": "true",
            }
        )

    server_info = StreamableHttpServerInfo(
        url=_PROVIDER_ENDPOINTS[provider],
        headers=headers,
    )

    return MCPToolset(server_info=server_info)
