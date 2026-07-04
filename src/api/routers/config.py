from fastapi import APIRouter, Request

router = APIRouter(tags=["config"])


@router.get("/config")
async def get_config(request: Request) -> dict:
    """Endpoint to retrieve current application configuration."""
    config = request.app.container.config()

    return {
        "app": {
            "environment": config["app"]["environment"],
            "port": config["app"]["port"],
        },
        "auth": {
            "frontend_base_url": config["auth"]["frontend_base_url"],
            "backend_base_url": config["auth"]["backend_base_url"],
        },
        "llm": {
            "chat_provider": config["llm"]["chat_provider"],
            "embedding_provider": config["llm"]["embedding_provider"],
            "chat_model": config["llm"]["chat_model"],
            "embedding_model": config["llm"]["embedding_model"],
        },
        "embedding": {
            "dimension": config["embedding"]["dimension"],
        },
        "neo4j": {
            "database": config["neo4j"]["database"],
            "index": config["neo4j"]["index"],
            "top_k": config["neo4j"]["top_k"],
        },
        "jira": {
            "configured": bool(config["jira"]["url"]),
        },
        "confluence": {
            "configured": bool(config["confluence"]["url"]),
        },
        "github": {
            "configured": bool(config["github"]["token"]),
        },
    }
