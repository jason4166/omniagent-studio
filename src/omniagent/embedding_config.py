"""One explicit embedding configuration for ingestion, retrieval and cache identity."""

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

from openai import OpenAI

from omniagent.credentials import resolve_secret, secret_configured
from omniagent.embeddings import EMBEDDING_DIMENSION, EmbeddingProvider, FakeEmbedding
from omniagent.errors import ErrorCode, PlatformError
from omniagent.openai_adapters import OpenAIEmbeddingProvider


@dataclass(frozen=True)
class EmbeddingConfiguration:
    provider: str = "fake"
    model: str = "fake-sha256-v1"
    base_url: str = ""

    @classmethod
    def from_environment(cls) -> "EmbeddingConfiguration":
        provider = os.environ.get("OMNIAGENT_EMBEDDING_PROVIDER", "fake")
        if provider == "fake":
            return cls()
        if provider != "primary":
            raise PlatformError(ErrorCode.VALIDATION, "Unknown embedding provider reference")
        model = os.environ.get("OMNIAGENT_EMBEDDING_MODEL", "")
        endpoint = os.environ.get("OMNIAGENT_EMBEDDING_BASE_URL", "")
        parsed = urlsplit(endpoint)
        if (
            not model
            or len(model) > 120
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not secret_configured("OMNIAGENT_EMBEDDING")
        ):
            raise PlatformError(ErrorCode.VALIDATION, "Real embedding configuration is incomplete")
        return cls(provider, model, endpoint.rstrip("/"))

    @property
    def version(self) -> str:
        if self.provider == "fake":
            return "fake-sha256-v1-1024"
        endpoint_hash = hashlib.sha256(self.base_url.encode()).hexdigest()[:16]
        return f"{self.provider}:{self.model}:{EMBEDDING_DIMENSION}:{endpoint_hash}"

    @contextmanager
    def configured(self) -> Iterator[EmbeddingProvider]:
        if self.provider == "fake":
            yield FakeEmbedding()
            return
        with OpenAI(
            api_key=resolve_secret("OMNIAGENT_EMBEDDING"),
            base_url=self.base_url,
            timeout=15,
            max_retries=0,
        ) as client:
            yield OpenAIEmbeddingProvider(
                client=client, model_name=self.model, timeout_seconds=15, index_version=self.version
            )
