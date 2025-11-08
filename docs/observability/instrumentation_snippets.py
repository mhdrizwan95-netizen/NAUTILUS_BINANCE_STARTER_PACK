"""
Reference instrumentation snippets for Nautilus services.
"""

# --- FastAPI (Ops API / UI API) ---------------------------------------------

import contextvars
import logging
import uuid

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_fastapi_instrumentator import Instrumentator


def configure_observability(app: FastAPI, service_name: str) -> None:
    # Prometheus HTTP request metrics
    Instrumentator().instrument(app).expose(app, include_in_schema=False, endpoint="/metrics")

    # OpenTelemetry tracing (OTLP/HTTP)
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel-collector:4318/v1/traces"))
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


# Usage:
# app = FastAPI()
# configure_observability(app, service_name="ops-api")

# --- Async Task Logging Context ---------------------------------------------

correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        correlation_id = correlation_id_ctx.get() or "unknown"
        extra = kwargs.setdefault("extra", {})
        extra["correlation_id"] = correlation_id
        return msg, kwargs


def bind_correlation_id(correlation_id: str | None = None) -> None:
    correlation_id_ctx.set(correlation_id or str(uuid.uuid4()))


logger = ContextAdapter(logging.getLogger("nautilus"), {})

# In request middleware:
#   bind_correlation_id(request.headers.get("X-Request-ID"))
#   logger.info("order submitted", extra={"event": "order.submitted"})
