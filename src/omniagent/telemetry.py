"""Local OpenTelemetry spans containing identifiers and measurements, never payloads."""

import hashlib
import json
import logging
import os
import re
from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from statistics import mean
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span, StatusCode
from sqlalchemy import Engine, event

from omniagent.redaction import redact_text

SAFE_ATTRIBUTES = frozenset(
    {
        "request_id",
        "thread_id",
        "run_id",
        "node_id",
        "tool_id",
        "tool_call_id",
        "approval_id",
        "profile_id",
        "provider_id",
        "model_id",
        "db_operation",
        "statement_hash",
        "http_method",
        "http_status",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "retry_count",
        "attempt",
        "degraded",
        "cache_hit",
        "error_code",
        "error_type",
        "cost_microusd",
        "node_name",
    }
)
identifiers: ContextVar[dict[str, str] | None] = ContextVar("trace_identifiers", default=None)
active_telemetry: ContextVar["Telemetry | None"] = ContextVar("active_telemetry", default=None)
logger = logging.getLogger("omniagent.telemetry")


class LocalExporter(SpanExporter):
    def __init__(self, *, log: bool = False) -> None:
        self.records: deque[dict[str, object]] = deque(maxlen=10000)
        self.lock = Lock()
        self.log = log
        if log and not logger.handlers:
            logger.addHandler(logging.StreamHandler())
            logger.setLevel(logging.INFO)
            logger.propagate = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self.lock:
            for item in spans:
                context = item.get_span_context()
                record: dict[str, object] = {
                    "name": item.name,
                    "trace_id": f"{context.trace_id:032x}" if context else "",
                    "span_id": f"{context.span_id:016x}" if context else "",
                    "parent_span_id": f"{item.parent.span_id:016x}" if item.parent else None,
                    "duration_ms": ((item.end_time or 0) - (item.start_time or 0)) / 1_000_000,
                    "status": item.status.status_code.name.lower(),
                    "attributes": {
                        k: v for k, v in (item.attributes or {}).items() if k in SAFE_ATTRIBUTES
                    },
                }
                self.records.append(record)
                if self.log:
                    logger.info(json.dumps(record, ensure_ascii=False))
        return SpanExportResult.SUCCESS

    def snapshot(self) -> list[dict[str, object]]:
        with self.lock:
            return list(self.records)


class Telemetry:
    def __init__(self, *, enabled: bool = True, configure_export: bool = False) -> None:
        self.enabled = enabled
        self.local = LocalExporter(
            log=configure_export and os.environ.get("OMNIAGENT_JSON_LOGS") == "1"
        )
        self.provider = TracerProvider(
            resource=Resource.create(
                {"service.name": "omniagent-studio", "service.version": "1.0.0-rc.1"}
            )
        )
        self.provider.add_span_processor(SimpleSpanProcessor(self.local))
        if configure_export and os.environ.get("OMNIAGENT_TRACE_EXPORTER", "none") != "none":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            endpoint = os.environ.get("OMNIAGENT_OTLP_ENDPOINT", "")
            target = urlsplit(endpoint)
            if (
                target.username
                or target.password
                or target.query
                or not (
                    target.scheme == "https"
                    or (
                        target.scheme == "http"
                        and target.hostname in {"localhost", "127.0.0.1", "otel"}
                    )
                )
            ):
                raise ValueError("OTLP requires an explicitly configured secure endpoint")
            reference = os.environ.get("OMNIAGENT_OTLP_HEADERS_REF", "OMNIAGENT_OTLP_HEADERS")
            if not re.fullmatch(r"OMNIAGENT_[A-Z0-9_]+", reference):
                raise ValueError("Invalid OTLP credential reference")
            headers = json.loads(os.environ.get(reference, "{}"))
            if not isinstance(headers, dict):
                raise ValueError("Invalid OTLP headers")
            self.provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=endpoint, headers=headers, timeout=3),
                    max_queue_size=512,
                    max_export_batch_size=128,
                )
            )
        self.tracer = self.provider.get_tracer("omniagent.v1")

    @contextmanager
    def activate(self, **ids: str) -> Iterator[None]:
        token = active_telemetry.set(self)
        identity_token = identifiers.set({**(identifiers.get() or {}), **ids})
        try:
            yield
        finally:
            identifiers.reset(identity_token)
            active_telemetry.reset(token)

    def shutdown(self) -> None:
        self.provider.shutdown()

    def metrics(self) -> dict[str, object]:
        records = self.local.snapshot()
        requests = [row for row in records if row["name"] == "api"]
        durations = sorted(float(str(row["duration_ms"])) for row in requests)

        def percentile(fraction: float) -> float | None:
            if not durations:
                return None
            index = (len(durations) - 1) * fraction
            left = int(index)
            right = min(left + 1, len(durations) - 1)
            return durations[left] + (durations[right] - durations[left]) * (index - left)

        models = [row for row in records if row["name"] == "llm"]
        attributes = [row["attributes"] for row in models if isinstance(row["attributes"], dict)]
        return {
            "scope": "last 10000 completed local spans; process lifetime; not durable billing",
            "requests": len(requests),
            "p50_ms": percentile(0.5),
            "p95_ms": percentile(0.95),
            "error_rate": mean(row["status"] == "error" for row in requests) if requests else None,
            "model_calls": len(models),
            "retrieval_calls": sum(row["name"] == "retrieval" for row in records),
            "tool_calls": sum(row["name"] == "tool" for row in records),
            **{
                field: sum(int(item.get(field, 0)) for item in attributes)
                for field in ("input_tokens", "output_tokens", "total_tokens")
            },
            "cost_microusd": 0
            if attributes and all(item.get("provider_id") == "fake" for item in attributes)
            else "unknown",
        }


@contextmanager
def correlation(**ids: str) -> Iterator[None]:
    token = identifiers.set({**(identifiers.get() or {}), **ids})
    try:
        yield
    finally:
        identifiers.reset(token)


def trace_metadata() -> dict[str, str]:
    context = trace.get_current_span().get_span_context()
    return {
        **(identifiers.get() or {}),
        **({"trace_id": f"{context.trace_id:032x}"} if context.is_valid else {}),
    }


@contextmanager
def span(name: str, **attributes: str | int | float | bool) -> Iterator[Span]:
    telemetry = active_telemetry.get()
    if telemetry is None or not telemetry.enabled:
        yield trace.INVALID_SPAN
        return
    safe = {
        key: redact_text(value)[:180] if isinstance(value, str) else value
        for key, value in {**(identifiers.get() or {}), **attributes}.items()
        if key in SAFE_ATTRIBUTES
    }
    with telemetry.tracer.start_as_current_span(
        name, attributes=safe, record_exception=False, set_status_on_exception=False
    ) as current:
        try:
            yield current
        except BaseException as exc:
            if type(exc).__name__ == "GraphInterrupt":
                raise
            current.set_status(StatusCode.ERROR)
            current.set_attribute("error_type", type(exc).__name__)
            code = getattr(exc, "code", "internal_error")
            current.set_attribute("error_code", redact_text(str(code))[:80])
            raise


def instrument_database(engine: Engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def before(
        connection: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: bool
    ) -> None:
        operation = statement.split(None, 1)[0].upper() if statement.strip() else "UNKNOWN"
        if operation not in {"SELECT", "INSERT", "UPDATE", "DELETE", "EXPLAIN", "CREATE", "ALTER"}:
            operation = "OTHER"
        manager = span(
            "database",
            db_operation=operation,
            statement_hash=hashlib.sha256(statement.encode()).hexdigest()[:16],
        )
        manager.__enter__()
        connection.info.setdefault("omni_spans", []).append(manager)

    @event.listens_for(engine, "after_cursor_execute")
    def after(connection: Any, *_args: Any) -> None:
        stack = connection.info.get("omni_spans", [])
        if stack:
            stack.pop().__exit__(None, None, None)

    @event.listens_for(engine, "handle_error")
    def failed(context: Any) -> None:
        connection = context.connection
        if connection is not None:
            stack = connection.info.get("omni_spans", [])
            if stack:
                exc = context.original_exception
                stack.pop().__exit__(type(exc), exc, exc.__traceback__)
