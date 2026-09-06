import time
from contextlib import contextmanager
from typing import Any

_metrics_store: dict[str, dict[str, Any]] = {}


@contextmanager
def track_step(session_id: str, step: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        store = _metrics_store.setdefault(session_id, {"turns": [], "last": {}})
        store["last"][step] = elapsed_ms


def record_turn(session_id: str, phase: str, extra: dict | None = None):
    store = _metrics_store.setdefault(session_id, {"turns": [], "last": {}})
    turn = {"phase": phase, **store["last"]}
    if extra:
        turn.update(extra)
    total = sum(v for k, v in turn.items() if k.endswith("_ms") or k in store["last"])
    if "last" in store and store["last"]:
        turn["total_ms"] = round(sum(store["last"].values()), 1)
    store["turns"].append(turn)
    store["last"] = {}


def get_metrics(session_id: str) -> dict:
    store = _metrics_store.get(session_id, {"turns": [], "last": {}})
    turns = store.get("turns", [])
    totals = [t.get("total_ms", 0) for t in turns if t.get("total_ms")]
    p50 = sorted(totals)[len(totals) // 2] if totals else 0
    return {
        "session_id": session_id,
        "turn_count": len(turns),
        "p50_turn_latency_ms": p50,
        "last_turn": store.get("last", {}),
        "history": turns[-10:],
    }
