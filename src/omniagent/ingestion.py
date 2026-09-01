import hashlib
import re
from collections.abc import Sequence
from io import BytesIO
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader

TXT_PARSER_VERSION = "txt-v1"
MARKDOWN_PARSER_VERSION = "markdown-v1"
PDF_PARSER_VERSION = "pypdf-6.16.2-v1"


class DocumentParseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UnsupportedDocumentError(DocumentParseError):
    pass


class ParsedUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.char_end - self.char_start != len(self.content):
            raise ValueError("unit range must match content length")
        return self


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^src-[0-9a-f]{64}$")
    knowledge_base_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str = Field(min_length=1)
    content: str = Field(min_length=1)
    units: tuple[ParsedUnit, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unit_locations(self) -> Self:
        for unit in self.units:
            if self.content[unit.char_start : unit.char_end] != unit.content:
                raise ValueError("unit range must locate its content in the document")
        return self


class ImportErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class SourceImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    source_name: str = Field(min_length=1)
    status: Literal[
        "imported",
        "duplicate",
        "rebuilt",
        "rejected",
        "unsupported",
        "failed",
    ]
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    chunk_count: int = Field(default=0, ge=0)
    error: ImportErrorDetail | None = None

    @model_validator(mode="after")
    def validate_error_state(self) -> Self:
        successful = self.status in {"imported", "duplicate", "rebuilt"}
        if successful == (self.error is not None):
            raise ValueError("error must be absent only for successful results")
        return self


def checksum_bytes(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def build_source_id(
    *,
    knowledge_base_id: str,
    source_name: str,
    checksum: str,
) -> str:
    identity = "\x1f".join((knowledge_base_id, source_name.casefold(), checksum))
    return f"src-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def normalize_text(text: str) -> str:
    normalized_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in normalized_lines).strip("\n")


def _decode_utf8(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("invalid_utf8", "Document must be valid UTF-8") from exc


def _build_document(
    *,
    raw_bytes: bytes,
    source_id: str,
    knowledge_base_id: str,
    source_name: str,
    title: str,
    mime_type: str,
    parser_version: str,
    unit_values: Sequence[tuple[str, int | None, str | None]],
) -> ParsedDocument:
    content_parts: list[str] = []
    units: list[ParsedUnit] = []
    cursor = 0

    for unit_content, page_number, section in unit_values:
        normalized = normalize_text(unit_content)
        if normalized == "":
            continue
        if content_parts:
            content_parts.append("\n\n")
            cursor += 2
        start = cursor
        content_parts.append(normalized)
        cursor += len(normalized)
        units.append(
            ParsedUnit(
                unit_index=len(units),
                content=normalized,
                char_start=start,
                char_end=cursor,
                page_number=page_number,
                section=section,
            )
        )

    content = "".join(content_parts)
    if content == "":
        raise DocumentParseError("empty_document", "Document contains no importable text")

    return ParsedDocument(
        source_id=source_id,
        knowledge_base_id=knowledge_base_id,
        source_name=source_name,
        title=title,
        mime_type=mime_type,
        checksum=checksum_bytes(raw_bytes),
        parser_version=parser_version,
        content=content,
        units=tuple(units),
    )


def parse_txt(
    *,
    raw_bytes: bytes,
    source_id: str,
    knowledge_base_id: str,
    source_name: str,
    title: str,
) -> ParsedDocument:
    return _build_document(
        raw_bytes=raw_bytes,
        source_id=source_id,
        knowledge_base_id=knowledge_base_id,
        source_name=source_name,
        title=title,
        mime_type="text/plain",
        parser_version=TXT_PARSER_VERSION,
        unit_values=[(_decode_utf8(raw_bytes), None, None)],
    )


def parse_markdown(
    *,
    raw_bytes: bytes,
    source_id: str,
    knowledge_base_id: str,
    source_name: str,
    title: str,
) -> ParsedDocument:
    text = normalize_text(_decode_utf8(raw_bytes))
    heading_pattern = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*#*\s*$")
    unit_values: list[tuple[str, int | None, str | None]] = []
    current_section = title
    current_lines: list[str] = []

    for line in text.split("\n"):
        heading = heading_pattern.match(line)
        if heading is None:
            current_lines.append(line)
            continue
        if normalize_text("\n".join(current_lines)):
            unit_values.append(("\n".join(current_lines), None, current_section))
        current_section = heading.group(2).strip()
        current_lines = []

    if normalize_text("\n".join(current_lines)):
        unit_values.append(("\n".join(current_lines), None, current_section))

    return _build_document(
        raw_bytes=raw_bytes,
        source_id=source_id,
        knowledge_base_id=knowledge_base_id,
        source_name=source_name,
        title=title,
        mime_type="text/markdown",
        parser_version=MARKDOWN_PARSER_VERSION,
        unit_values=unit_values,
    )


def parse_pdf(
    *,
    raw_bytes: bytes,
    source_id: str,
    knowledge_base_id: str,
    source_name: str,
    title: str,
) -> ParsedDocument:
    try:
        reader = PdfReader(BytesIO(raw_bytes), strict=False)
        unit_values = [
            (page.extract_text() or "", page_index + 1, None)
            for page_index, page in enumerate(reader.pages)
        ]
    except Exception as exc:
        raise DocumentParseError("invalid_pdf", "PDF could not be parsed") from exc

    if not any(normalize_text(content) for content, _, _ in unit_values):
        raise UnsupportedDocumentError(
            "scanned_pdf_unsupported",
            "PDF has no extractable text; OCR is not supported",
        )

    return _build_document(
        raw_bytes=raw_bytes,
        source_id=source_id,
        knowledge_base_id=knowledge_base_id,
        source_name=source_name,
        title=title,
        mime_type="application/pdf",
        parser_version=PDF_PARSER_VERSION,
        unit_values=unit_values,
    )
