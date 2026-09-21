"""Embedding allowance failures must stop the paid request and expose the daily category."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from omniagent.access import AccessService
from omniagent.embeddings import FakeEmbedding
from omniagent.errors import ErrorCode, PlatformError
from omniagent.identity import DevUserContext
from omniagent.metered_embedding import MeteredEmbedding

pytestmark = pytest.mark.unit


def test_exhausted_daily_embedding_allowance_never_calls_provider(monkeypatch):
    access = Mock(spec=AccessService)
    access.settings = SimpleNamespace(mode="password")

    def exhausted(_reservations, *, error_code=ErrorCode.RATE_LIMIT):
        raise PlatformError(error_code)

    access.reserve.side_effect = exhausted
    provider = FakeEmbedding()
    embed = Mock(wraps=provider.embed)
    monkeypatch.setattr(provider, "embed", embed)
    actor = DevUserContext(user_id="embedding-test-user", role="member")
    metered = MeteredEmbedding(provider, access, actor)
    texts = ["退款规则"]

    with pytest.raises(PlatformError) as caught:
        metered.embed(texts)

    assert caught.value.code == ErrorCode.DAILY_QUOTA
    assert caught.value.status_code == 429
    access.validate_actor.assert_called_once_with(actor)
    units = len(texts[0].encode("utf-8")) * 2
    access.reserve.assert_called_once_with(
        [("embedding:" + actor.user_id, units, 2000000), ("embedding:global", units, 10000000)],
        error_code=ErrorCode.DAILY_QUOTA,
    )
    embed.assert_not_called()
