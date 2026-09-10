import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from omniagent.connectors import build_adapters, build_registry, catalog
from omniagent.database import build_engine
from omniagent.embeddings import FakeEmbedding
from omniagent.errors import PlatformError
from omniagent.identity import DevUserContext, authenticate
from omniagent.postgres_retrieval import HybridRetriever
from omniagent.presets import seed
from omniagent.semantic_cache import SemanticCacheRow, SemanticRetriever, canonical_terms, manifest
from omniagent.session_store import SessionStore, digest

pytestmark = pytest.mark.integration


@pytest.fixture
def cache():
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    store = SessionStore(build_engine(url))
    definitions, _ = catalog("127.0.0.1", 18081)
    seed(store, definitions)
    registry = build_registry(store, build_adapters("127.0.0.1", 18081), definitions)
    actor = authenticate("Bearer local-demo-member").model_copy(
        update={"user_id": "cache-test-" + uuid4().hex}
    )
    profile = store.profile("hr", actor)
    inner = HybridRetriever(store.factory, FakeEmbedding(), text_query_operator="or")
    instance = SemanticRetriever(store, profile, actor, registry, inner)
    namespace = digest(manifest(store, profile, actor, registry))
    yield instance
    with store.factory.begin() as db:
        db.execute(delete(SemanticCacheRow).where(SemanticCacheRow.namespace == namespace))
    store.engine.dispose()


def test_semantic_alias_reuses_evidence_but_keeps_negations_and_numbers_distinct(cache):
    first = cache.retrieve_hits(["hr-kb"], "annual leave")
    assert first and cache.last_hit is False
    assert cache.retrieve_hits(["hr-kb"], "年假") == first
    assert cache.last_hit is True
    assert canonical_terms("annual leave 10") != canonical_terms("annual leave 20")
    assert canonical_terms("not annual leave") != canonical_terms("annual leave")


def test_cache_permission_and_versions_partition_keys(cache):
    original = manifest(cache.store, cache.profile, cache.actor, cache.registry)
    for field, value in [
        ("version", 2),
        ("model", "different-model"),
        ("prompt_version_id", "support:v1"),
        ("knowledge_base_ids", ["support-kb"]),
    ]:
        changed = cache.profile.model_copy(update={field: value})
        assert manifest(cache.store, changed, cache.actor, cache.registry) != original
    other = cache.actor.model_copy(update={"role": "viewer"})
    assert manifest(cache.store, cache.profile, other, cache.registry) != original
    with pytest.raises(PlatformError):
        cache.retrieve_hits(["sales-kb"], "annual leave")
    cache.actor = DevUserContext(user_id="outsider", role="member", profile_ids=())
    with pytest.raises(PlatformError):
        cache.retrieve_hits(["hr-kb"], "annual leave")


@pytest.mark.parametrize("corruption", ["schema", "foreign_kb", "content", "expired", "locator"])
def test_corrupt_stale_or_cross_kb_cache_is_never_trusted(cache, corruption):
    expected = cache.retrieve_hits(["hr-kb"], "annual leave")
    from datetime import UTC, datetime

    from omniagent.session_store import digest

    namespace = digest(manifest(cache.store, cache.profile, cache.actor, cache.registry))
    with cache.store.factory.begin() as db:
        row = db.scalar(select(SemanticCacheRow).where(SemanticCacheRow.namespace == namespace))
        if corruption == "schema":
            row.schema_version = 2
        elif corruption == "expired":
            row.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
        elif corruption == "locator":
            row.hits = [
                {**hit, "source_locator": {**hit["source_locator"], "source_name": "forged.txt"}}
                for hit in row.hits
            ]
        else:
            field = "knowledge_base_id" if corruption == "foreign_kb" else "content"
            row.hits = [{**hit, field: "forged"} for hit in row.hits]
    assert cache.retrieve_hits(["hr-kb"], "annual leave") == expected
    assert cache.last_hit is False
