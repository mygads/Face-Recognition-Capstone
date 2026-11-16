"""Benchmark SINTETIS recognition-core (CPU saja, tanpa kamera/model).

Mengukur DUA tahap yang tidak butuh model ONNX:
1. Gallery matching (cosine, NumPy bila tersedia).
2. Temporal consensus (frames-to-accept + keputusan ganti orang).

Yang SENGAJA DIKECUALIKAN (tetap MANUAL HARDWARE TEST REQUIRED):
YuNet detect, SFace embed, capture kamera/USB, DB, jaringan, SSE.
Angka di sini BUKAN klaim FPS kiosk; hanya baseline regresi performa
CPU untuk matching + temporal di mesin ini.

Usage:
    PYTHONPATH=libs/recognition-core/src python3 scripts/bench_recognition_synthetic.py
"""

from __future__ import annotations

import os
import platform
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "libs", "recognition-core", "src"))

import random

from recognition_core.domain import (
    CandidateMatch,
    FaceEmbedding,
    FaceQuality,
    FrameObservation,
    GalleryEntry,
    LivenessDecision,
)
from recognition_core.matching import CosineSimilarityMatcher
from recognition_core.temporal import MultiFrameDecisionEngine, TemporalDecisionConfig


def _unit_vector(rng: random.Random, dim: int) -> tuple[float, ...]:
    vals = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = sum(v * v for v in vals) ** 0.5
    return tuple(v / norm for v in vals)


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return float("nan")
    ordered = sorted(data)
    rank = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[rank]


def bench_matching() -> dict[str, float | int | str]:
    rng = random.Random(20261117)
    dim = 128
    matcher = CosineSimilarityMatcher(minimum_similarity=0.5)
    out: dict[str, float | int | str] = {}
    for students, templates_each in ((30, 3), (100, 3), (300, 3)):
        gallery = [
            GalleryEntry(
                student_id=UUID(int=i + 1),
                embedding=FaceEmbedding(
                    values=_unit_vector(rng, dim),
                    model_name="synthetic",
                    model_version="test-1",
                    normalized=True,
                ),
            )
            for i in range(students)
            for _ in range(templates_each)
        ]
        probe = FaceEmbedding(
            values=gallery[0].embedding.values,
            model_name="synthetic",
            model_version="test-1",
            normalized=True,
        )
        matcher.match(probe, gallery)  # pemanasan (NumPy path/cache)
        lat: list[float] = []
        iters = 500
        for _ in range(iters):
            start = time.perf_counter()
            top = matcher.match(probe, gallery)
            lat.append((time.perf_counter() - start) * 1000.0)
        assert top and top[0].student_id == gallery[0].student_id
        key = f"match_gallery_{len(gallery)}"
        out[f"{key}_p50_ms"] = round(_percentile(lat, 50), 3)
        out[f"{key}_p95_ms"] = round(_percentile(lat, 95), 3)
        out[f"{key}_queries"] = iters
    out["match_numpy"] = (
        "ya" if getattr(matcher, "_numpy", None) is not None else "tidak"
    )
    return out


def _decide_frames(
    engine: MultiFrameDecisionEngine,
    student: UUID,
    other: UUID,
    frames: int,
    switch_at: int | None,
    start: datetime,
) -> tuple[int | None, str, str]:
    accepted_at: int | None = None
    last_state = ""
    identities: list[str] = []
    for i in range(frames):
        who = student if switch_at is None or i < switch_at else other
        top = (
            CandidateMatch(student_id=who, similarity=0.9),
            CandidateMatch(student_id=other if who == student else student, similarity=0.3),
        )
        obs = FrameObservation(track_id="track-sintetis", captured_at=start + timedelta(milliseconds=66 * i))
        decision = engine.decide(
            obs,
            top,
            FaceQuality(score=0.9, acceptable=True),
            LivenessDecision(state="disabled", required=False),
        )
        last_state = decision.state
        if decision.state == "accepted" and accepted_at is None:
            accepted_at = i + 1
        if decision.state == "accepted" and decision.decision.student_id is not None:
            identities.append(str(decision.decision.student_id))
    identity_note = (
        f"tetap {identities[-1]}" if identities and len(set(identities)) == 1
        else f"campur {sorted(set(identities))}" if identities
        else "tak ada accept"
    )
    return accepted_at, last_state, identity_note


def bench_temporal() -> dict[str, float | int | str]:
    config = TemporalDecisionConfig(
        min_top1_similarity=0.5,
        min_top1_top2_margin=0.2,
        minimum_agreeing_frames=3,
        sample_every_n_frames=2,
    )
    alice, bob = UUID(int=101), UUID(int=202)
    start = datetime.now(UTC)
    engine = MultiFrameDecisionEngine(config)
    t0 = time.perf_counter()
    accepted_at, _, identity_same = _decide_frames(engine, alice, bob, 40, None, start)
    same_ms = (time.perf_counter() - t0) * 1000.0

    engine2 = MultiFrameDecisionEngine(config)
    t0 = time.perf_counter()
    accepted_switch, state_switch, identity_switch = _decide_frames(engine2, alice, bob, 40, 6, start)
    switch_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "temporal_same_person_accept_frame": accepted_at if accepted_at is not None else -1,
        "temporal_same_person_identity": identity_same,
        "temporal_same_person_40frames_ms": round(same_ms, 3),
        "temporal_switch_person_accept_frame": accepted_switch if accepted_switch is not None else -1,
        "temporal_switch_person_final_state": state_switch,
        "temporal_switch_identity": identity_switch,
        "temporal_switch_40frames_ms": round(switch_ms, 3),
    }


def main() -> int:
    print("BENCHMARK SINTETIS recognition-core (BUKAN pengukuran kamera/hardware)")
    print(f"mesin={platform.machine()} cpu_logis={os.cpu_count()} python={platform.python_version()}")
    result: dict[str, float | int | str] = {}
    result.update(bench_matching())
    result.update(bench_temporal())
    for key in sorted(result):
        print(f"{key}={result[key]}")
    print("CATATAN: deteksi YuNet + embedding SFace + kamera TIDAK termasuk;")
    print("angka FPS kiosk tetap MANUAL HARDWARE TEST REQUIRED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
