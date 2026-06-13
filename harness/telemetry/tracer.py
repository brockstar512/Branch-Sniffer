"""OpenTelemetry setup — cross-cutting instrumentation.

Every pillar emits spans and metrics through this module. By default uses the
console exporter (zero infrastructure). Set DOG_OTLP_ENDPOINT environment
variable to ship to an OTLP backend (Honeycomb, Grafana Cloud, Uptrace).
"""
from __future__ import annotations

import os

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_initialized = False


def init_telemetry() -> None:
    """Idempotent. Call once at process start (the CLI does)."""
    global _initialized
    if _initialized:
        return

    resource = Resource.create({"service.name": "dog"})

    # Tracer
    tracer_provider = TracerProvider(resource=resource)
    if os.getenv("DOG_OTLP_ENDPOINT"):
        # When user sets this, ship to OTLP backend
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # Meter
    reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=60_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    _initialized = True


# Convenience accessors after init
def get_tracer():
    return trace.get_tracer("dog")


def get_meter():
    return metrics.get_meter("dog")
