from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

from openai import OpenAI
from sqlalchemy import delete

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from omniagent.chunking import ChunkingConfig  # noqa: E402
from omniagent.database import build_engine, build_session_factory  # noqa: E402
from omniagent.db_models import KnowledgeBaseRow  # noqa: E402
from omniagent.grounding_runtime import GroundingRuntime  # noqa: E402
from omniagent.openai_adapters import (  # noqa: E402
    OpenAICompatibleChatProvider,
    OpenAIEmbeddingProvider,
)
from omniagent.postgres_repositories import SqlAlchemyKnowledgeRepository  # noqa: E402
from omniagent.postgres_retrieval import HybridRetriever  # noqa: E402
from omniagent.profiles import KnowledgeBase  # noqa: E402
from omniagent.services import KnowledgeBaseService  # noqa: E402

EMBEDDING_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
EMBEDDING_MODEL = "embedding-3"
LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-v4-flash"


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def main() -> None:
    database_url = required_environment("OMNIAGENT_DATABASE_URL")
    knowledge_base_id = f"kb-day13-real-{uuid4().hex}"
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    embedding = OpenAIEmbeddingProvider(
        client=OpenAI(
            api_key=required_environment("ZHIPUAI_API_KEY"),
            base_url=EMBEDDING_BASE_URL,
        ),
        model_name=EMBEDDING_MODEL,
        dimension=1024,
        timeout_seconds=30.0,
    )
    llm = OpenAICompatibleChatProvider(
        OpenAI(
            api_key=required_environment("DEEPSEEK_API_KEY"),
            base_url=LLM_BASE_URL,
        )
    )
    raw_document = (
        "# 财务报销\n"
        "员工必须在费用发生后30天内提交报销申请。\n\n"
        "# 年假制度\n"
        "正式员工每年享有10天年假。\n"
    ).encode()

    try:
        with session_factory.begin() as session:
            service = KnowledgeBaseService(
                SqlAlchemyKnowledgeRepository(session, embedding),
                ChunkingConfig(
                    chunk_size=100,
                    overlap=0,
                    version="day13-real-smoke-v1",
                ),
            )
            service.create(
                KnowledgeBase(
                    knowledge_base_id=knowledge_base_id,
                    name="Day13 real provider smoke",
                )
            )
            imported = service.import_source(
                knowledge_base_id=knowledge_base_id,
                source_name="employee-policy.md",
                mime_type="text/markdown",
                raw_bytes=raw_document,
            )

        retriever = HybridRetriever(
            session_factory,
            embedding,
            top_k=2,
            candidate_k=5,
            text_query_operator="or",
        )
        runtime = GroundingRuntime(
            retriever=retriever,
            provider=llm,
            model=LLM_MODEL,
            max_content_characters=500,
        )
        result = runtime.run(
            profile_id="day13-real-smoke",
            thread_id="day13-real-smoke-thread",
            query="公司规定报销申请最晚什么时候提交？",
            authorized_knowledge_base_ids=[knowledge_base_id],
        )

        if imported.status != "imported":
            raise RuntimeError(f"Expected an imported document, got {imported.status}")
        if result.status != "succeeded":
            error_code = result.error.code if result.error is not None else "unknown"
            raise RuntimeError(f"Grounded answer was not produced: {error_code}")
        if not result.claims or not result.citations:
            raise RuntimeError("Grounded answer is missing claims or citations")
        if any(citation.knowledge_base_id != knowledge_base_id for citation in result.citations):
            raise RuntimeError("Grounded answer contains an unauthorized citation")

        citation = result.citations[0]
        print(f"import_status={imported.status} chunks={imported.chunk_count}")
        print(f"runtime_status={result.status} route={result.route}")
        print(f"claims={len(result.claims)} citations={len(result.citations)}")
        print(f"citation_label={citation.citation_label}")
        print(f"citation_source={citation.source_locator.source_name}")
        print(f"content_hash_length={len(citation.content_sha256)}")
        print("authorized_only=True")
    finally:
        with session_factory.begin() as session:
            session.execute(
                delete(KnowledgeBaseRow).where(
                    KnowledgeBaseRow.knowledge_base_id == knowledge_base_id
                )
            )
        engine.dispose()


if __name__ == "__main__":
    main()
