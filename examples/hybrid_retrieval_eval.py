from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from omniagent.database import build_engine, build_session_factory  # noqa: E402
from omniagent.db_models import KnowledgeBaseRow  # noqa: E402
from omniagent.embeddings import FakeEmbedding  # noqa: E402
from omniagent.postgres_repositories import SqlAlchemyKnowledgeRepository  # noqa: E402
from omniagent.postgres_retrieval import (  # noqa: E402
    HybridRetriever,
    PgTextRetriever,
    PgVectorRetriever,
)
from omniagent.profiles import KnowledgeBase  # noqa: E402
from omniagent.retrieval_evaluation import (  # noqa: E402
    PreparedRetrievalEvalCorpus,
    RetrievalEvalReport,
    RetrievalEvalResult,
    RetrievalEvalRunConfig,
    RetrievalEvalSummary,
    RetrievalHitsProvider,
    RetrievalMode,
    load_retrieval_eval_cases,
    load_retrieval_eval_corpus,
    run_retrieval_eval,
    summarize_retrieval_eval,
)

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://omniagent:omniagent-local-only@127.0.0.1:5432/omniagent"
)
DEFAULT_DATASET_PATH = PROJECT_ROOT / "evals" / "retrieval-v1.jsonl"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "evals" / "retrieval-v1" / "corpus.json"
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "evals" / "artifacts" / "retrieval"
LIMITATIONS = (
    "Vector scores use deterministic FakeEmbedding and do not demonstrate semantic quality.",
    "PostgreSQL simple text search does not provide professional Chinese word segmentation.",
    "No-answer evaluation measures empty retrieval only; no confidence threshold is configured.",
)
REPORT_MODES: tuple[RetrievalMode, ...] = ("vector", "text", "hybrid")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic Day 12 PostgreSQL retrieval evaluation."
    )
    parser.add_argument("--run-name", choices=("baseline", "candidate"), default="baseline")
    parser.add_argument(
        "--database-url", default=os.getenv("OMNIAGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--rank-constant", type=int, default=60)
    parser.add_argument("--text-query-operator", choices=("and", "or"), default="and")
    return parser.parse_args()


def compute_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_corpus_hash(corpus: PreparedRetrievalEvalCorpus) -> str:
    digest = hashlib.sha256()
    digest.update(corpus.manifest.model_dump_json().encode("utf-8"))
    for source in corpus.sources:
        digest.update(source.document.source_id.encode("utf-8"))
        digest.update(source.raw_bytes)
    return digest.hexdigest()


def replace_evaluation_corpus(
    corpus: PreparedRetrievalEvalCorpus,
    session_factory: sessionmaker[Session],
    embedding: FakeEmbedding,
) -> None:
    knowledge_base_ids = [
        knowledge_base.knowledge_base_id for knowledge_base in corpus.manifest.knowledge_bases
    ]

    with session_factory.begin() as session:
        session.execute(
            delete(KnowledgeBaseRow).where(
                KnowledgeBaseRow.knowledge_base_id.in_(knowledge_base_ids)
            )
        )
        session.flush()

        repository = SqlAlchemyKnowledgeRepository(session, embedding)
        for knowledge_base in corpus.manifest.knowledge_bases:
            repository.save_knowledge_base(
                KnowledgeBase(
                    knowledge_base_id=knowledge_base.knowledge_base_id,
                    name=knowledge_base.name,
                )
            )
        session.flush()

        for source in corpus.sources:
            repository.save_source(source.document, source.raw_bytes)
            repository.save_chunks(
                source.document.source_id,
                list(source.chunks),
            )


def build_markdown(report: RetrievalEvalReport) -> str:
    lines = [
        f"# Day 12 Retrieval Evaluation: {report.run_name}",
        "",
        f"- Dataset: `{report.dataset_version}`",
        f"- Dataset SHA-256: `{report.dataset_hash}`",
        f"- Corpus SHA-256: `{report.corpus_hash}`",
        f"- Embedding: `{report.embedding_model}` ({report.embedding_dimension} dimensions)",
        f"- Chunks: {report.corpus_chunk_count}",
        f"- Config: `top_k={report.config.top_k}`, `candidate_k={report.config.candidate_k}`, "
        f"`rank_constant={report.config.rank_constant}`, "
        f"`text_query_operator={report.config.text_query_operator}`",
        "",
        "## Summary",
        "",
        "| Mode | Recall@1 | Recall@3 | Recall@5 | MRR | No-answer empty rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for mode in REPORT_MODES:
        summary = report.summaries[mode]
        no_answer_rate = (
            "n/a" if summary.no_answer_empty_rate is None else f"{summary.no_answer_empty_rate:.4f}"
        )
        lines.append(
            f"| {mode} | {summary.recall_at_1:.4f} | {summary.recall_at_3:.4f} | "
            f"{summary.recall_at_5:.4f} | {summary.mrr:.4f} | {no_answer_rate} |"
        )

    lines.extend(["", "## Lowest-scoring cases", ""])
    for mode in REPORT_MODES:
        lines.extend(
            [
                f"### {mode}",
                "",
                "| Case | Category | Recall@5 | RR | Returned |",
                "|---|---|---:|---:|---:|",
            ]
        )
        ordered = sorted(
            report.results[mode],
            key=lambda result: (
                1.0
                if result.recall_at_5 is None and not result.hits
                else result.recall_at_5 or 0.0,
                result.reciprocal_rank or 0.0,
                result.case_id,
            ),
        )
        for result in ordered[:3]:
            recall = "n/a" if result.recall_at_5 is None else f"{result.recall_at_5:.4f}"
            reciprocal_rank = (
                "n/a" if result.reciprocal_rank is None else f"{result.reciprocal_rank:.4f}"
            )
            lines.append(
                f"| {result.case_id} | {result.category} | {recall} | "
                f"{reciprocal_rank} | {len(result.hits)} |"
            )
        lines.append("")

    lines.extend(["## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines) + "\n"


def save_report(report: RetrievalEvalReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(f"{report.model_dump_json(indent=2)}\n", encoding="utf-8")
    markdown_path.write_text(build_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    args = parse_args()
    config = RetrievalEvalRunConfig(
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        rank_constant=args.rank_constant,
        text_query_operator=args.text_query_operator,
    )
    corpus = load_retrieval_eval_corpus(args.manifest_path)
    cases = load_retrieval_eval_cases(args.dataset_path)
    embedding = FakeEmbedding()
    engine = build_engine(args.database_url)
    session_factory = build_session_factory(engine)

    try:
        replace_evaluation_corpus(corpus, session_factory, embedding)
        retrievers: dict[RetrievalMode, RetrievalHitsProvider] = {
            "vector": PgVectorRetriever(session_factory, embedding, top_k=config.top_k),
            "text": PgTextRetriever(
                session_factory,
                embedding,
                top_k=config.top_k,
                query_operator=config.text_query_operator,
            ),
            "hybrid": HybridRetriever(
                session_factory,
                embedding,
                top_k=config.top_k,
                candidate_k=config.candidate_k,
                rank_constant=config.rank_constant,
                text_query_operator=config.text_query_operator,
            ),
        }
        results: dict[RetrievalMode, tuple[RetrievalEvalResult, ...]] = {}
        summaries: dict[RetrievalMode, RetrievalEvalSummary] = {}
        for mode, retriever in retrievers.items():
            mode_results = run_retrieval_eval(cases, retriever, retrieval_mode=mode)
            results[mode] = tuple(mode_results)
            summaries[mode] = summarize_retrieval_eval(mode_results)

        report = RetrievalEvalReport(
            run_name=args.run_name,
            created_at=datetime.now(UTC),
            dataset_version=corpus.manifest.dataset_version,
            dataset_hash=compute_file_hash(args.dataset_path),
            corpus_hash=compute_corpus_hash(corpus),
            embedding_model=embedding.model_name,
            embedding_dimension=embedding.dimension,
            corpus_chunk_count=sum(len(source.chunks) for source in corpus.sources),
            config=config,
            summaries=summaries,
            results=results,
            limitations=LIMITATIONS,
        )
        json_path, markdown_path = save_report(
            report,
            args.artifacts_root / args.run_name,
        )
    finally:
        engine.dispose()

    for mode in REPORT_MODES:
        summary = report.summaries[mode]
        no_answer_rate = (
            "n/a" if summary.no_answer_empty_rate is None else f"{summary.no_answer_empty_rate:.4f}"
        )
        print(
            mode,
            f"Recall@1={summary.recall_at_1:.4f}",
            f"Recall@3={summary.recall_at_3:.4f}",
            f"Recall@5={summary.recall_at_5:.4f}",
            f"MRR={summary.mrr:.4f}",
            f"no_answer_empty_rate={no_answer_rate}",
        )
    print("json_report =", json_path)
    print("markdown_report =", markdown_path)


if __name__ == "__main__":
    main()
