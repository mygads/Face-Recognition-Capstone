from __future__ import annotations

from presensi_edge_agent.camera_metrics import CameraRuntimeMetrics, read_camera_frame


def test_latency_summary_reports_recent_camera_read_percentiles() -> None:
    metrics = CameraRuntimeMetrics(requested_fps=30)

    assert metrics.latency_summary() is None
    for duration_ms in range(1, 21):
        metrics.record_read_latency(float(duration_ms))

    assert metrics.latency_summary() == {"p50_ms": 10.0, "p95_ms": 19.0}


def test_read_camera_frame_records_only_successful_frame_latency() -> None:
    metrics = CameraRuntimeMetrics(requested_fps=30)

    class FakeCamera:
        def __init__(self, result: tuple[bool, object | None]) -> None:
            self.result = result

        def read(self) -> tuple[bool, object | None]:
            return self.result

    ok, frame, duration_ms = read_camera_frame(FakeCamera((True, object())), metrics)
    assert ok is True
    assert frame is not None
    assert duration_ms >= 0
    assert metrics.latency_summary() is None

    for _ in range(19):
        read_camera_frame(FakeCamera((True, object())), metrics)

    summary = metrics.latency_summary()
    assert summary is not None
    read_camera_frame(FakeCamera((False, None)), metrics)
    assert metrics.latency_summary() == summary
