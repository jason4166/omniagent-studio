"""PostgreSQL ingestion contracts; natural-language quality is evaluated separately."""

import json
import os
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from omniagent.connectors import catalog
from omniagent.database import build_engine
from omniagent.db_models import ChunkRow, SourceRow
from omniagent.embeddings import FakeEmbedding
from omniagent.eval_platform import EvalCase, EvalDataset
from omniagent.identity import DevUserContext
from omniagent.ingestion import checksum_bytes
from omniagent.postgres_retrieval import PgTextRetriever
from omniagent.presets import seed
from omniagent.session_store import SessionStore

pytestmark = pytest.mark.integration
DATASET_DIRECTORY = Path("evals/knowledge-v1")
DATASET = EvalDataset.model_validate_json(
    (DATASET_DIRECTORY / "cases.json").read_text(encoding="utf-8")
)
CONTRACTS = json.loads((DATASET_DIRECTORY / "retrieval-contracts.json").read_text(encoding="utf-8"))
TERMS = {entry["case_id"]: entry["query_terms"] for entry in CONTRACTS}
KB_IDS = ("hr-kb", "support-kb", "sales-kb")


@pytest.fixture(scope="module")
def knowledge_store() -> Iterator[SessionStore]:
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    store = SessionStore(build_engine(url))
    seed(store, catalog("127.0.0.1", 18081)[0])
    try:
        yield store
    finally:
        store.engine.dispose()


def test_knowledge_dataset_has_independent_labels_and_balanced_splits() -> None:
    assert DATASET.dataset_version == "omniagent-knowledge-v1-expanded-policies"
    assert len({case.case_id for case in DATASET.cases}) == 24
    assert len(CONTRACTS) == len(TERMS) == 24
    assert set(TERMS) == {case.case_id for case in DATASET.cases}
    assert Counter((case.profile_id, case.split) for case in DATASET.cases) == {
        (profile, split): 4 for profile in ("hr", "support", "sales") for split in ("dev", "test")
    }
    for case in DATASET.cases:
        assert case.expected_route == "retrieve"
        assert case.expected_outcome == "answer"
        assert case.relevant_sources and case.answer_quality is not None
        assert TERMS[case.case_id] != case.query


@pytest.mark.parametrize("case", DATASET.cases, ids=lambda case: case.case_id)
def test_seeded_evidence_is_indexed_locatable_and_kb_scoped(
    knowledge_store: SessionStore, case: EvalCase
) -> None:
    actor = DevUserContext(
        user_id="knowledge-coverage-contract", role="member", profile_ids=(case.profile_id,)
    )
    profile = knowledge_store.profile(case.profile_id, actor)
    retriever = PgTextRetriever(knowledge_store.factory, FakeEmbedding(), top_k=5)
    hits = retriever.retrieve_hits(profile.knowledge_base_ids, TERMS[case.case_id])
    assert hits, f"No PostgreSQL text-index match for {case.case_id}"
    assert set(case.relevant_sources) <= {hit.source_locator.source_name for hit in hits}
    assert all(hit.knowledge_base_id in profile.knowledge_base_ids for hit in hits)

    with knowledge_store.factory() as db:
        for hit in hits:
            source = db.get(SourceRow, hit.source_id)
            assert source is not None and source.knowledge_base_id == hit.knowledge_base_id
            assert source.source_name == hit.source_locator.source_name
            assert source.content[hit.source_locator.char_start : hit.source_locator.char_end] == (
                hit.content
            )
            path = Path("presets/knowledge") / source.knowledge_base_id / source.source_name
            assert source.checksum == checksum_bytes(path.read_bytes())
            assert source.raw_bytes == path.read_bytes()

    other_kbs = [
        identifier for identifier in KB_IDS if identifier not in profile.knowledge_base_ids
    ]
    foreign_hits = retriever.retrieve_hits(other_kbs, TERMS[case.case_id])
    assert all(hit.knowledge_base_id in other_kbs for hit in foreign_hits)
    assert not {hit.source_id for hit in hits} & {hit.source_id for hit in foreign_hits}


def test_repeated_seed_preserves_source_and_chunk_identities(knowledge_store: SessionStore) -> None:
    def snapshot() -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
        with knowledge_store.factory() as db:
            sources = list(
                db.execute(
                    select(
                        SourceRow.source_id,
                        SourceRow.checksum,
                        SourceRow.knowledge_base_id,
                        SourceRow.created_at,
                    )
                    .where(SourceRow.knowledge_base_id.in_(KB_IDS))
                    .order_by(SourceRow.source_id)
                ).tuples()
            )
            chunks = list(
                db.execute(
                    select(
                        ChunkRow.chunk_id,
                        ChunkRow.source_id,
                        ChunkRow.embedding_model,
                        ChunkRow.content,
                        ChunkRow.created_at,
                    )
                    .where(ChunkRow.knowledge_base_id.in_(KB_IDS))
                    .order_by(ChunkRow.chunk_id)
                ).tuples()
            )
            return [tuple(row) for row in sources], [tuple(row) for row in chunks]

    before = snapshot()
    assert before[0] and before[1]
    repeated = seed(knowledge_store, catalog("127.0.0.1", 18081)[0])
    assert repeated["created_profiles"] == 0
    assert snapshot() == before
