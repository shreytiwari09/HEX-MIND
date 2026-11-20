"""OpenTelemetry setup. ADK creates its own spans (agent, model and tool calls) on the global
tracer provider; the TelemetryHub adds our attributes to them and opens spans for CrewAI crews.

Spans are exported to a collector when `HEXMIND_OTLP_ENDPOINT` is set (e.g. the Jaeger in
docker-compose.yml: `docker compose --profile observability up -d`), and always kept in Postgres
(`trace_spans`, telemetry/span_store.py) so the app can show traces with no collector at all.
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

_provider: TracerProvider | None = None


def setup_tracing(settings: Settings) -> TracerProvider:
    """Install the global tracer provider once per process (OTel allows a single one)."""
    global _provider
    if _provider is None:
        current = trace.get_tracer_provider()
        if isinstance(current, TracerProvider):  # already set, e.g. by tests
            _provider = current
        else:
            _provider = TracerProvider(resource=Resource.create({"service.name": "hexmind"}))
            trace.set_tracer_provider(_provider)
        if settings.store_traces:
            from app.telemetry.span_store import PostgresSpanProcessor

            add_span_processor(PostgresSpanProcessor(settings.database_url))
        if settings.otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
            )
    return _provider


def add_span_processor(processor: SpanProcessor) -> None:
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.add_span_processor(processor)
