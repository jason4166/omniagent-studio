from pathlib import Path

import pytest

from omniagent.ingestion import (
    DocumentParseError,
    UnsupportedDocumentError,
    build_source_id,
    checksum_bytes,
    normalize_text,
    parse_markdown,
    parse_pdf,
    parse_txt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def source_id(raw_bytes: bytes, source_name: str) -> str:
    return build_source_id(
        knowledge_base_id="kb-demo",
        source_name=source_name,
        checksum=checksum_bytes(raw_bytes),
    )


def test_parse_txt_returns_unified_parsed_document() -> None:
    raw_bytes = b"Synthetic refund policy.\n"

    document = parse_txt(
        raw_bytes=raw_bytes,
        source_id=source_id(raw_bytes, "synthetic-refund-policy.txt"),
        knowledge_base_id="kb-demo",
        source_name="synthetic-refund-policy.txt",
        title="Synthetic Refund Policy",
    )

    assert document.mime_type == "text/plain"
    assert document.parser_version == "txt-v1"
    assert document.checksum == checksum_bytes(raw_bytes)
    assert document.content == "Synthetic refund policy."
    assert document.units[0].char_start == 0
    assert document.units[0].char_end == len(document.content)


def test_normalize_text_unifies_line_endings_and_trailing_spaces() -> None:
    assert normalize_text("Alpha  \r\nBeta \r\n") == "Alpha\nBeta"


def test_parse_txt_rejects_invalid_utf8() -> None:
    raw_bytes = b"\xff\xfe"

    with pytest.raises(DocumentParseError, match="valid UTF-8") as exc_info:
        parse_txt(
            raw_bytes=raw_bytes,
            source_id=source_id(raw_bytes, "invalid.txt"),
            knowledge_base_id="kb-demo",
            source_name="invalid.txt",
            title="Invalid",
        )

    assert exc_info.value.code == "invalid_utf8"


def test_parse_markdown_creates_section_units_with_locations() -> None:
    raw_bytes = (FIXTURES / "synthetic-handbook.md").read_bytes()

    document = parse_markdown(
        raw_bytes=raw_bytes,
        source_id=source_id(raw_bytes, "synthetic-handbook.md"),
        knowledge_base_id="kb-demo",
        source_name="synthetic-handbook.md",
        title="Synthetic Handbook",
    )

    assert [unit.section for unit in document.units] == [
        "Synthetic Handbook",
        "Returns",
        "Warranty",
    ]
    assert document.units[1].content == "Returns are accepted within 30 days."
    for unit in document.units:
        assert document.content[unit.char_start : unit.char_end] == unit.content


def test_parse_markdown_without_headings_uses_document_title_as_section() -> None:
    raw_bytes = b"Synthetic body only."

    document = parse_markdown(
        raw_bytes=raw_bytes,
        source_id=source_id(raw_bytes, "body.md"),
        knowledge_base_id="kb-demo",
        source_name="body.md",
        title="Body",
    )

    assert len(document.units) == 1
    assert document.units[0].section == "Body"


def test_parse_markdown_supports_synthetic_chinese_text() -> None:
    raw_bytes = "# 合成手册\n\n退货期限为三十天。".encode()

    document = parse_markdown(
        raw_bytes=raw_bytes,
        source_id=source_id(raw_bytes, "synthetic-zh.md"),
        knowledge_base_id="kb-demo",
        source_name="synthetic-zh.md",
        title="合成手册",
    )

    assert document.units[0].section == "合成手册"
    assert document.units[0].content == "退货期限为三十天。"


def test_parse_markdown_strips_optional_closing_heading_markers() -> None:
    raw_bytes = b"## Warranty ##\n\nSynthetic warranty text."

    document = parse_markdown(
        raw_bytes=raw_bytes,
        source_id=source_id(raw_bytes, "heading.md"),
        knowledge_base_id="kb-demo",
        source_name="heading.md",
        title="Heading",
    )

    assert document.units[0].section == "Warranty"


def test_parse_empty_txt_returns_classified_error() -> None:
    raw_bytes = b"\r\n  \r\n"

    with pytest.raises(DocumentParseError) as exc_info:
        parse_txt(
            raw_bytes=raw_bytes,
            source_id=source_id(raw_bytes, "empty.txt"),
            knowledge_base_id="kb-demo",
            source_name="empty.txt",
            title="Empty",
        )

    assert exc_info.value.code == "empty_document"


def test_parse_pdf_creates_one_unit_per_text_page() -> None:
    raw_bytes = (FIXTURES / "synthetic-support-guide.pdf").read_bytes()

    document = parse_pdf(
        raw_bytes=raw_bytes,
        source_id=source_id(raw_bytes, "synthetic-support-guide.pdf"),
        knowledge_base_id="kb-demo",
        source_name="synthetic-support-guide.pdf",
        title="Synthetic Support Guide",
    )

    assert document.mime_type == "application/pdf"
    assert document.parser_version == "pypdf-6.16.2-v1"
    assert [unit.page_number for unit in document.units] == [1, 2]
    assert "Returns are accepted within 30 days." in document.units[0].content
    assert "Warranty requests require an order number." in document.units[1].content


def test_parse_scanned_pdf_returns_explicit_unsupported_error() -> None:
    raw_bytes = (FIXTURES / "synthetic-scanned-page.pdf").read_bytes()

    with pytest.raises(UnsupportedDocumentError) as exc_info:
        parse_pdf(
            raw_bytes=raw_bytes,
            source_id=source_id(raw_bytes, "synthetic-scanned-page.pdf"),
            knowledge_base_id="kb-demo",
            source_name="synthetic-scanned-page.pdf",
            title="Synthetic Scanned Page",
        )

    assert exc_info.value.code == "scanned_pdf_unsupported"
    assert exc_info.value.message == "PDF has no extractable text; OCR is not supported"


def test_parse_invalid_pdf_returns_generic_error_without_local_path() -> None:
    raw_bytes = b"not a pdf"

    with pytest.raises(DocumentParseError) as exc_info:
        parse_pdf(
            raw_bytes=raw_bytes,
            source_id=source_id(raw_bytes, "broken.pdf"),
            knowledge_base_id="kb-demo",
            source_name="broken.pdf",
            title="Broken",
        )

    assert exc_info.value.code == "invalid_pdf"
    assert exc_info.value.message == "PDF could not be parsed"
    assert "D:\\" not in exc_info.value.message


def test_source_id_is_stable_for_same_kb_name_and_checksum() -> None:
    checksum = checksum_bytes(b"same content")

    first = build_source_id(
        knowledge_base_id="kb-demo",
        source_name="guide.txt",
        checksum=checksum,
    )
    second = build_source_id(
        knowledge_base_id="kb-demo",
        source_name="guide.txt",
        checksum=checksum,
    )

    assert first == second


def test_same_content_with_different_names_keeps_distinct_source_ids() -> None:
    checksum = checksum_bytes(b"same content")

    first = build_source_id(
        knowledge_base_id="kb-demo",
        source_name="guide-a.txt",
        checksum=checksum,
    )
    second = build_source_id(
        knowledge_base_id="kb-demo",
        source_name="guide-b.txt",
        checksum=checksum,
    )

    assert first != second
