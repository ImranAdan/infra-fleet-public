"""Gunicorn hooks. Loaded with --config python:load_harness.gunicorn_config."""

from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics


def child_exit(server, worker):
    # Drop a dead worker's live gauges so /metrics does not report them forever.
    GunicornInternalPrometheusMetrics.mark_process_dead_on_child_exit(worker.pid)
