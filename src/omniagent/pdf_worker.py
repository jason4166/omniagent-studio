"""Fixed-purpose PDF parser process with bounded resources and JSON-only output."""

import json
import sys
from io import BytesIO

from pypdf import PdfReader, filters


def main() -> None:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    for name in ("ZLIB_MAX_OUTPUT_LENGTH", "LZW_MAX_OUTPUT_LENGTH", "RUN_LENGTH_MAX_OUTPUT_LENGTH"):
        setattr(filters, name, 2_000_000)
    try:
        raw = sys.stdin.buffer.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("Input limit")
        reader = PdfReader(BytesIO(raw), strict=True)
        if reader.is_encrypted or len(reader.pages) > 50:
            raise ValueError("Document limit")
        pages = []
        size = 0
        for page in reader.pages:
            content = page.extract_text() or ""
            size += len(content.encode("utf-8"))
            if size > 500_000:
                raise ValueError("Text limit")
            pages.append(content)
        result = json.dumps(pages, ensure_ascii=True).encode()
        if len(result) > 3_100_000:
            raise ValueError("Output limit")
        sys.stdout.buffer.write(result)
    except Exception:
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
