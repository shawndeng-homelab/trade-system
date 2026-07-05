"""OpenTelemetry initialization and common helpers.

Sets up a global :class:`~opentelemetry.sdk.trace.TracerProvider` and
:class:`~opentelemetry.sdk.metrics.MeterProvider` with an OTLP exporter,
so that spans and metrics flow to a Grafana Tempo / OTel Collector endpoint.

The initialization is idempotent — calling :func:`init_observability` more
than once is safe.

"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry import trace

from trade_system_core.config import ObservabilityConfig


_initialized = False


def init_observability(config: ObservabilityConfig) -> None:
    """Initialize the global OTel TracerProvider and MeterProvider.

    Configures an OTLP gRPC exporter pointed at *config.otlp_endpoint*.
    Idempotent: subsequent calls are no-ops.

    Parameters
    ----------
    config : ObservabilityConfig
        Observability configuration from the YAML run config.

    """
    global _initialized
    if _initialized or not config.enabled:
        return

    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter  # noqa: PLC0415
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # noqa: PLC0415
    from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # noqa: PLC0415
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

    resource = Resource.create({"service.name": config.service_name})

    # ── Tracing ─────────────────────────────────────────────────────────
    span_exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint)
    span_processor = BatchSpanProcessor(span_exporter)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)

    # ── Metrics ─────────────────────────────────────────────────────────
    metric_exporter = OTLPMetricExporter(endpoint=config.otlp_endpoint)
    metric_reader = PeriodicExportingMetricReader(
        exporter=metric_exporter,
        export_interval_millis=config.export_interval_ms,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    _initialized = True


def get_tracer(name: str = "trade_system_core") -> trace.Tracer:
    """Return an OTel tracer from the global provider."""
    return trace.get_tracer(name)


def get_meter(name: str = "trade_system_core") -> metrics.Meter:
    """Return an OTel meter from the global provider."""
    return metrics.get_meter(name)


def shutdown_observability() -> None:
    """Flush and shut down OTel providers.  Call before process exit."""
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415

    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()

    from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415

    meter_provider = metrics.get_meter_provider()
    if isinstance(meter_provider, MeterProvider):
        meter_provider.shutdown()

    global _initialized
    _initialized = False
