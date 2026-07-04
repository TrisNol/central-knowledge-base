from typing import Any

from haystack.utils import Secret

# ollama providers
try:
    from haystack_integrations.components.embedders.ollama import OllamaTextEmbedder
    from haystack_integrations.components.embedders.ollama.document_embedder import (
        OllamaDocumentEmbedder,
    )
    from haystack_integrations.components.generators.ollama import OllamaChatGenerator
except Exception:
    OllamaChatGenerator = OllamaTextEmbedder = OllamaDocumentEmbedder = None

# OpenAI providers
try:
    from haystack.components.embedders import OpenAIDocumentEmbedder, OpenAITextEmbedder
    from haystack.components.generators.chat import OpenAIChatGenerator
except Exception:
    OpenAIChatGenerator = OpenAITextEmbedder = OpenAIDocumentEmbedder = None

# AzureOpenAI providers
try:
    from haystack.components.embedders import (
        AzureOpenAIDocumentEmbedder,
        AzureOpenAITextEmbedder,
    )
    from haystack.components.generators.chat import AzureOpenAIChatGenerator
except Exception:
    AzureOpenAIChatGenerator = AzureOpenAITextEmbedder = AzureOpenAIDocumentEmbedder = (
        None
    )


def create_llm_generator(
    provider: str,
    model: str | None,
    host: str | None,
    openai_api_key: str | None,
    azure_deployment_name: str | None,
    azure_openai_endpoint: str | None,
    azure_openai_api_key: str | None,
) -> Any:
    """Create and return a chat generator instance for the given provider.

    The returned object is a Haystack generator component (e.g. OllamaChatGenerator
    or OpenAIChatGenerator/OpenAIGenerator). Raises ImportError if the
    requested provider's integration is not available.
    """
    provider = provider.lower()
    if provider == "openai":
        if OpenAIChatGenerator is not None:
            return OpenAIChatGenerator(
                model=model,
                api_key=Secret.from_token(openai_api_key),
            )
        raise ImportError(
            "OpenAI chat generator is not available. Install haystack with OpenAI support."
        )
    elif provider == "azure":
        if AzureOpenAIChatGenerator is None:
            raise ImportError(
                "Azure OpenAI chat generator is not available. Install haystack with Azure OpenAI support."
            )
        return OpenAIChatGenerator(
            api_base_url=azure_openai_endpoint,
            api_key=Secret.from_token(azure_openai_api_key),
            model=azure_deployment_name or model,
        )
    elif provider == "ollama":
        if OllamaChatGenerator is None:
            raise ImportError(
                "Ollama chat generator is not available. Install haystack-integrations with Ollama support."
            )
        return OllamaChatGenerator(model=model, url=host)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def create_text_embedder(
    provider: str,
    model: str | None,
    host: str | None,
    openai_api_key: str | None,
    azure_openai_endpoint: str | None,
    azure_openai_api_key: str | None,
    azure_openai_api_version: str | None,
    embedding_dimension: int,
) -> Any:
    """Create and return a text embedder instance for the given provider.

    This is intended for query embeddings.
    """
    provider = provider.lower()
    if provider == "openai":
        if OpenAITextEmbedder is None:
            raise ImportError(
                "OpenAI text embedder is not available. Install haystack with OpenAI support."
            )
        return OpenAITextEmbedder(
            model=model,
            api_key=Secret.from_token(openai_api_key),
            dimensions=embedding_dimension,
        )
    elif provider == "azure":
        if AzureOpenAITextEmbedder is None:
            raise ImportError(
                "Azure OpenAI text embedder is not available. Install haystack with Azure OpenAI support."
            )
        return AzureOpenAITextEmbedder(
            azure_deployment=model,
            azure_endpoint=azure_openai_endpoint,
            api_key=Secret.from_token(azure_openai_api_key),
            api_version=azure_openai_api_version,
            dimensions=embedding_dimension,
        )
    elif provider == "ollama":
        if OllamaTextEmbedder is None:
            raise ImportError(
                "Ollama text embedder is not available. Install haystack-integrations with Ollama support."
            )
        return OllamaTextEmbedder(model=model, url=host)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def create_document_embedder(
    provider: str,
    model: str | None,
    host: str | None,
    openai_api_key: str | None,
    azure_openai_endpoint: str | None,
    azure_openai_api_key: str | None,
    azure_openai_api_version: str | None,
    embedding_dimension: int,
) -> Any:
    """Create and return a document embedder for indexing.

    This is intended to be passed to the indexing pipeline.
    """
    provider = provider.lower()
    if provider == "openai":
        if OpenAIDocumentEmbedder is None:
            raise ImportError(
                "OpenAI document embedder is not available. Install haystack with OpenAI support."
            )
        return OpenAIDocumentEmbedder(
            model=model,
            api_key=Secret.from_token(openai_api_key),
            dimensions=embedding_dimension,
        )
    elif provider == "azure":
        if AzureOpenAIDocumentEmbedder is None:
            raise ImportError(
                "Azure OpenAI document embedder is not available. Install haystack with Azure OpenAI support."
            )
        return AzureOpenAIDocumentEmbedder(
            azure_deployment=model,
            azure_endpoint=azure_openai_endpoint,
            api_key=Secret.from_token(azure_openai_api_key),
            api_version=azure_openai_api_version,
            dimensions=embedding_dimension,
        )
    elif provider == "ollama":
        if OllamaDocumentEmbedder is None:
            raise ImportError(
                "Ollama document embedder is not available. Install haystack-integrations with Ollama support."
            )
        return OllamaDocumentEmbedder(model=model, url=host)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
