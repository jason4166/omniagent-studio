from pathlib import Path

from omniagent.chunking import ChunkingConfig, chunk_document
from omniagent.ingestion import (
    DocumentParseError,
    ImportErrorDetail,
    SourceImportResult,
    UnsupportedDocumentError,
    build_source_id,
    checksum_bytes,
    parse_markdown,
    parse_pdf,
    parse_txt,
)
from omniagent.profiles import AgentProfile, AgentProfilePatch, KnowledgeBase
from omniagent.repositories import AgentProfileRepository, KnowledgeRepository


class AgentProfileAlreadyExistsError(RuntimeError):
    pass


class AgentProfileNotFoundError(RuntimeError):
    pass


class AgentProfileVersionConflictError(RuntimeError):
    pass


class AgentProfileService:
    def __init__(self, repository: AgentProfileRepository) -> None:
        self._repository = repository

    def create(self, profile: AgentProfile) -> AgentProfile:
        existing = self._repository.get(profile.profile_id)
        if existing is not None:
            raise AgentProfileAlreadyExistsError(
                f"Agent profile '{profile.profile_id}' already exists"
            )

        self._repository.save(profile)
        return profile

    def get(self, profile_id: str) -> AgentProfile:
        profile = self._repository.get(profile_id)

        if profile is None:
            raise AgentProfileNotFoundError(f"Agent profile '{profile_id}' was not found")

        return profile

    def update(
        self,
        profile_id: str,
        patch: AgentProfilePatch,
    ) -> AgentProfile:
        current = self.get(profile_id)

        if current.version != patch.expected_version:
            raise AgentProfileVersionConflictError(
                f"Agent profile '{profile_id}' version conflict: "
                f"expected {patch.expected_version}, current {current.version}"
            )

        updates = patch.model_dump(
            exclude_unset=True,
            exclude={"expected_version"},
        )

        candidate = current.model_dump()
        candidate.update(updates)
        candidate["version"] = current.version + 1

        updated = AgentProfile.model_validate(candidate)

        self._repository.save(updated)
        return updated


class KnowledgeBaseAlreadyExistsError(RuntimeError):
    pass


class KnowledgeBaseNotFoundError(RuntimeError):
    pass


class KnowledgeBaseService:
    MAX_UPLOAD_BYTES = 1024 * 1024
    _SUPPORTED_TYPES = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".pdf": "application/pdf",
    }

    def __init__(
        self,
        repository: KnowledgeRepository,
        chunking_config: ChunkingConfig | None = None,
    ) -> None:
        self._repository = repository
        self._chunking_config = chunking_config or ChunkingConfig(
            chunk_size=500,
            overlap=50,
            version="day10-v1",
        )

    def create(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        if self._repository.get_knowledge_base(knowledge_base.knowledge_base_id) is not None:
            raise KnowledgeBaseAlreadyExistsError(
                f"Knowledge base '{knowledge_base.knowledge_base_id}' already exists"
            )
        self._repository.save_knowledge_base(knowledge_base)
        return knowledge_base

    def import_source(
        self,
        *,
        knowledge_base_id: str,
        source_name: str,
        mime_type: str,
        raw_bytes: bytes,
    ) -> SourceImportResult:
        if self._repository.get_knowledge_base(knowledge_base_id) is None:
            raise KnowledgeBaseNotFoundError(f"Knowledge base '{knowledge_base_id}' was not found")

        safe_name = source_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
        if safe_name == "":
            return self._error_result(
                source_name="unnamed",
                status="rejected",
                code="missing_filename",
                message="Upload must include a filename",
            )

        if len(raw_bytes) > self.MAX_UPLOAD_BYTES:
            return self._error_result(
                source_name=safe_name,
                status="rejected",
                code="upload_too_large",
                message=f"Upload exceeds the {self.MAX_UPLOAD_BYTES}-byte limit",
            )

        checksum = checksum_bytes(raw_bytes)
        source_id = build_source_id(
            knowledge_base_id=knowledge_base_id,
            source_name=safe_name,
            checksum=checksum,
        )

        extension = Path(safe_name).suffix.casefold()
        expected_mime = self._SUPPORTED_TYPES.get(extension)
        if expected_mime is None:
            return self._error_result(
                source_name=safe_name,
                source_id=source_id,
                checksum=checksum,
                status="rejected",
                code="unsupported_extension",
                message="Only .txt, .md, .markdown, and .pdf files are supported",
            )
        if mime_type.casefold() != expected_mime:
            return self._error_result(
                source_name=safe_name,
                source_id=source_id,
                checksum=checksum,
                status="rejected",
                code="mime_type_mismatch",
                message="Upload MIME type does not match the file extension",
            )

        existing = self._repository.get_source(source_id)
        if existing is not None:
            existing_chunks = self._repository.list_chunks(source_id)
            config_matches = bool(existing_chunks) and all(
                chunk.metadata.chunking_version == self._chunking_config.version
                and chunk.metadata.chunk_size == self._chunking_config.chunk_size
                and chunk.metadata.overlap == self._chunking_config.overlap
                for chunk in existing_chunks
            )
            if not config_matches:
                rebuilt_chunks = chunk_document(existing, self._chunking_config)
                self._repository.save_chunks(source_id, rebuilt_chunks)
                return SourceImportResult(
                    source_id=source_id,
                    source_name=safe_name,
                    status="rebuilt",
                    checksum=checksum,
                    chunk_count=len(rebuilt_chunks),
                )
            return SourceImportResult(
                source_id=source_id,
                source_name=safe_name,
                status="duplicate",
                checksum=checksum,
                chunk_count=len(existing_chunks),
            )

        parser = {
            ".txt": parse_txt,
            ".md": parse_markdown,
            ".markdown": parse_markdown,
            ".pdf": parse_pdf,
        }[extension]

        try:
            document = parser(
                raw_bytes=raw_bytes,
                source_id=source_id,
                knowledge_base_id=knowledge_base_id,
                source_name=safe_name,
                title=Path(safe_name).stem,
            )
        except UnsupportedDocumentError as exc:
            return self._error_result(
                source_name=safe_name,
                source_id=source_id,
                checksum=checksum,
                status="unsupported",
                code=exc.code,
                message=exc.message,
            )
        except DocumentParseError as exc:
            return self._error_result(
                source_name=safe_name,
                source_id=source_id,
                checksum=checksum,
                status="failed",
                code=exc.code,
                message=exc.message,
            )

        chunks = chunk_document(document, self._chunking_config)
        self._repository.save_source(document, raw_bytes)
        self._repository.save_chunks(source_id, chunks)
        return SourceImportResult(
            source_id=source_id,
            source_name=safe_name,
            status="imported",
            checksum=checksum,
            chunk_count=len(chunks),
        )

    @staticmethod
    def _error_result(
        *,
        source_name: str,
        status: str,
        code: str,
        message: str,
        source_id: str | None = None,
        checksum: str | None = None,
    ) -> SourceImportResult:
        return SourceImportResult.model_validate(
            {
                "source_id": source_id,
                "source_name": source_name,
                "status": status,
                "checksum": checksum,
                "error": ImportErrorDetail(code=code, message=message),
            }
        )
