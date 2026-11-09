"""Structured logging, OpenTelemetry trace IDs, Prometheus metrics, and uniform errors (T021)."""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.privacy.masker import mask_pii

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

TURN_LATENCY_HISTOGRAM = Histogram(
    "rag_turn_latency_seconds",
    "End-to-end turn latency in seconds",
    ["kind"],
    buckets=(0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 30.0, 45.0),
)
TURN_TTFT_HISTOGRAM = Histogram(
    "rag_turn_ttft_seconds",
    "Time to first token in seconds",
    buckets=(0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0),
)
TURN_COUNTER = Counter(
    "rag_turns_total",
    "Total Q&A turns by kind",
    ["kind"],
)
LLM_TOKENS_COUNTER = Counter(
    "rag_llm_tokens_total",
    "Total LLM tokens consumed",
    ["direction", "model"],
)
LLM_COST_COUNTER = Counter(
    "rag_llm_cost_usd_total",
    "Estimated LLM cost in USD",
    ["model"],
)


def get_current_trace_id() -> str:
    tid = _trace_id_var.get()
    if not tid:
        tid = uuid.uuid4().hex
        _trace_id_var.set(tid)
    return tid


def set_current_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


def _scrub_pii_processor(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Ensure no raw PII is ever emitted in structured logs (FR-021, Constitution III)."""
    for key, val in list(event_dict.items()):
        if isinstance(val, str):
            event_dict[key], _ = mask_pii(val)
    if "trace_id" not in event_dict:
        event_dict["trace_id"] = get_current_trace_id()
    return event_dict


def configure_observability() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            _scrub_pii_processor,
            structlog.processors.JSONRenderer(),
        ],
        cache_logger_on_first_use=False,
    )


class AppError(Exception):
    """Domain error mapped to uniform JSON error envelope."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def install_observability(app: FastAPI) -> None:
    configure_observability()

    @app.middleware("http")
    async def trace_and_password_guard_middleware(request: Request, call_next: Any) -> Any:
        incoming_tid = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        set_current_trace_id(incoming_tid)
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = incoming_tid
        _ = time.perf_counter() - start
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "trace_id": get_current_trace_id(),
                }
            },
            headers={"X-Trace-Id": get_current_trace_id()},
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            code = str(detail["code"])
            message = str(detail.get("message", code))
        else:
            code = f"http_{exc.status_code}"
            message = str(detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "trace_id": get_current_trace_id(),
                }
            },
            headers={"X-Trace-Id": get_current_trace_id()},
        )

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(
            generate_latest().decode("utf-8"),
            media_type=CONTENT_TYPE_LATEST,
        )
