"""Credential and embedding contracts run offline; live quality is a separate opt-in gate."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from omniagent import credentials
from omniagent.embedding_config import EmbeddingConfiguration
from omniagent.embeddings import EmbeddingProviderError
from omniagent.errors import PlatformError
from omniagent.openai_adapters import OpenAIEmbeddingProvider
from omniagent.redaction import redact_text

pytestmark = [pytest.mark.unit, pytest.mark.security]


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    for suffix in ("API_KEY", "API_KEY_FILE", "BASE_URL", "MODEL", "PROVIDER"):
        monkeypatch.delenv("OMNIAGENT_EMBEDDING_" + suffix, raising=False)
    monkeypatch.setattr(credentials, "_loaded_secrets", set())


def test_file_reference_resolves_and_redacts_without_serializing_secret(tmp_path, monkeypatch):
    path = tmp_path / "credential"
    synthetic = "synthetic-test-credential-value"
    path.write_text(synthetic + "\n", encoding="utf-8")
    monkeypatch.setenv("OMNIAGENT_EMBEDDING_API_KEY_FILE", str(path))
    assert credentials.resolve_secret("OMNIAGENT_EMBEDDING") == synthetic
    assert synthetic not in redact_text("upstream echoed " + synthetic)
    monkeypatch.setenv("OMNIAGENT_EMBEDDING_API_KEY", "conflicting-synthetic-value")
    with pytest.raises(PlatformError, match="Choose one"):
        credentials.resolve_secret("OMNIAGENT_EMBEDDING")


@pytest.mark.parametrize("content", [b"short", b"x" * 8193, b"\xff"])
def test_invalid_secret_file_fails_closed(tmp_path, monkeypatch, content):
    path = tmp_path / "credential"
    path.write_bytes(content)
    monkeypatch.setenv("OMNIAGENT_EMBEDDING_API_KEY_FILE", str(path))
    with pytest.raises(PlatformError, match="reference unavailable"):
        credentials.resolve_secret("OMNIAGENT_EMBEDDING")


def test_real_embedding_requires_explicit_secure_configuration(monkeypatch):
    assert EmbeddingConfiguration.from_environment().provider == "fake"
    monkeypatch.setenv("OMNIAGENT_EMBEDDING_PROVIDER", "primary")
    with pytest.raises(PlatformError):
        EmbeddingConfiguration.from_environment()
    monkeypatch.setenv("OMNIAGENT_EMBEDDING_MODEL", "embedding-3")
    monkeypatch.setenv("OMNIAGENT_EMBEDDING_API_KEY_FILE", "/run/secrets/embedding")
    monkeypatch.setenv("OMNIAGENT_EMBEDDING_BASE_URL", "https://example.invalid/v1")
    config = EmbeddingConfiguration.from_environment()
    assert "embedding-3:1024:" in config.version
    assert "secrets" not in repr(config)
    monkeypatch.setenv("OMNIAGENT_EMBEDDING_BASE_URL", "http://example.invalid/v1")
    with pytest.raises(PlatformError):
        EmbeddingConfiguration.from_environment()
    assert (
        config.version
        != EmbeddingConfiguration("primary", "embedding-3", "https://other.invalid").version
    )


def test_embedding_batches_preserve_all_input_order_and_actual_usage():
    endpoint = Mock()
    endpoint.create.side_effect = lambda **args: SimpleNamespace(
        data=[
            SimpleNamespace(index=i, embedding=[float(value)])
            for i, value in reversed(list(enumerate(args["input"])))
        ],
        usage=SimpleNamespace(prompt_tokens=len(args["input"]) * 2),
    )
    provider = OpenAIEmbeddingProvider(client=SimpleNamespace(embeddings=endpoint))
    assert provider.embed([str(i) for i in range(35)]) == [[float(i)] for i in range(35)]
    assert [len(call.kwargs["input"]) for call in endpoint.create.call_args_list] == [16, 16, 3]
    assert provider.last_input_tokens == 70
    assert all(0 < call.kwargs["timeout"] <= 30 for call in endpoint.create.call_args_list)


def test_duplicate_embedding_indices_are_not_silently_reordered_or_retried():
    endpoint = Mock()
    endpoint.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[0.1])] * 2, usage=None
    )
    provider = OpenAIEmbeddingProvider(client=SimpleNamespace(embeddings=endpoint))
    with pytest.raises(EmbeddingProviderError, match="indices"):
        provider.embed(["first", "second"])
    assert endpoint.create.call_count == 1
