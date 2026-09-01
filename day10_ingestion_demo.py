import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=24)
    parser.add_argument("--overlap", type=int, default=6)
    parser.add_argument("--text")
    return parser.parse_args()


def main() -> None:
    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root / "src"))

    from omniagent.chunking import ChunkingConfig
    from omniagent.profiles import KnowledgeBase
    from omniagent.repositories import InMemoryKnowledgeRepository
    from omniagent.services import KnowledgeBaseService

    args = parse_args()
    repository = InMemoryKnowledgeRepository()
    if args.text is None:
        source_path = project_root / "tests" / "fixtures" / "documents" / "synthetic-policy.txt"
        source_name = source_path.name
        raw_bytes = source_path.read_bytes()
    else:
        source_name = "manual.txt"
        raw_bytes = str(args.text).encode("utf-8")
    initial_service = KnowledgeBaseService(
        repository,
        ChunkingConfig(chunk_size=30, overlap=5, version="demo-v1"),
    )
    initial_service.create(KnowledgeBase(knowledge_base_id="kb-demo", name="Synthetic Demo"))
    imported = initial_service.import_source(
        knowledge_base_id="kb-demo",
        source_name=source_name,
        mime_type="text/plain",
        raw_bytes=raw_bytes,
    )
    changed_service = KnowledgeBaseService(
        repository,
        ChunkingConfig(
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            version=f"demo-{args.chunk_size}-{args.overlap}",
        ),
    )
    changed = changed_service.import_source(
        knowledge_base_id="kb-demo",
        source_name=source_name,
        mime_type="text/plain",
        raw_bytes=raw_bytes,
    )

    print(f"initial_status={imported.status} chunk_count={imported.chunk_count}")
    print(f"changed_status={changed.status} chunk_count={changed.chunk_count}")
    for chunk in repository.list_chunks(changed.source_id or ""):
        metadata = chunk.metadata
        print(
            f"{chunk.chunk_index}: [{metadata.char_start}, {metadata.char_end}) "
            f"id={chunk.chunk_id[:16]} content={chunk.content!r}"
        )


if __name__ == "__main__":
    main()
