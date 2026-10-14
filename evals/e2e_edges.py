"""Edge cases against a running backend: bad input, wrong order, double submits, long answers, parallel candidates.

Usage: venv/bin/python evals/e2e_edges.py [base_url] [--outage]
--outage: the server was started with an invalid AI key; a full interview must still finish with a report.
Prints one PASS/FAIL line per check and exits non-zero if any check fails.
"""

import sys
import threading
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = next((arg for arg in sys.argv[1:] if arg.startswith("http")), "http://127.0.0.1:8001")
OUTAGE = "--outage" in sys.argv
DAF = ROOT / "data" / "sample_daf_upsc_format_1.pdf"
GOOD = (
    "Growing up in Panchkula, I saw how planned sectors keep traffic away from homes because zoning separates uses. "
    "For example, Sector 5 has green belts and wide roads. However, rents have risen and many workers live far away. "
    "So planning must include affordable housing near jobs."
)
LONG = " ".join([GOOD] * 5)  # about 300 words: well past a 90-second answer
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=240)


def start(http: httpx.Client) -> tuple[str, str]:
    with DAF.open("rb") as pdf:
        upload = http.post("/upload-daf", files={"file": (DAF.name, pdf, "application/pdf")}, data={"interview_mode": "quick"})
    upload.raise_for_status()
    session = upload.json()["session_id"]
    first = http.post("/start-interview", data={"session_id": session}).json()
    return session, first["question"]


def interview(answers: list[str]) -> tuple[str, dict]:
    """Runs a quick interview with these answers (the last one repeats) and returns the report."""
    http = client()
    session, _ = start(http)
    for number in range(30):
        turn = http.post("/respond", data={"session_id": session, "text_answer": answers[min(number, len(answers) - 1)]})
        turn.raise_for_status()
        if turn.json().get("interview_complete"):
            break
    return session, http.get(f"/feedback-report/{session}").json()["report"]


def runOrderChecks() -> None:
    http = client()
    check("unknown session -> 404", http.post("/respond", data={"session_id": "nope", "text_answer": "hi"}).status_code == 404)
    check("unknown session report -> 404", http.get("/feedback-report/nope").status_code == 404)
    bad = http.post("/upload-daf", files={"file": ("cv.pdf", b"not really a pdf", "application/pdf")}, data={"interview_mode": "quick"})
    check("corrupt upload -> clear 4xx, not a crash", 400 <= bad.status_code < 500, f"status={bad.status_code}")
    session, _ = start(http)
    early = http.get(f"/feedback-report/{session}")
    check("report before the end -> 400", early.status_code == 400, f"status={early.status_code}")
    again = http.post("/start-interview", data={"session_id": session})
    check("double start -> same session continues", again.status_code == 200)


def runAnswerChecks() -> None:
    session, report = interview([LONG, "skip", GOOD])
    first = (report.get("question_feedback") or [{}])[0]
    check("300-word answer judged whole", (first.get("length") or {}).get("verdict") == "too_long", str(first.get("length")))
    check("skip inside a real interview scores as skipped", report["question_feedback"][1]["status"] == "skipped")
    late = client().post("/respond", data={"session_id": session, "text_answer": "one more answer"})
    after = client().get(f"/feedback-report/{session}").json()["report"]
    check("answer after the end -> 409, report unchanged", late.status_code == 409 and after["scores"] == report["scores"], f"status={late.status_code}")


def runParallelChecks() -> None:
    reports: dict[str, dict] = {}

    def run(name: str, answers: list[str]) -> None:
        reports[name] = interview(answers)[1]

    threads = [
        threading.Thread(target=run, args=("skips", ["skip"])),
        threading.Thread(target=run, args=("good", [GOOD])),
        threading.Thread(target=run, args=("mixed", [GOOD, "skip"])),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Each report must match ONLY its own answers: all skipped / later turns skipped / no turn skipped.
    statuses = {name: [row["status"] for row in report["question_feedback"]] for name, report in reports.items()}
    own = (
        all(status == "skipped" for status in statuses["skips"])
        and all(status == "skipped" for status in statuses["mixed"][1:])
        and "skipped" not in statuses["good"]
    )
    check("3 candidates at once: no mix-ups", own, str(statuses))


def runOutageCheck() -> None:
    session, report = interview([GOOD, "skip", GOOD, "Yes sir.", GOOD])
    rows = report.get("question_feedback") or []
    check("AI outage: interview still finishes with a report", bool(rows) and "coverage" in report, f"rows={len(rows)}")
    check("AI outage: skips still 0, answers still scored",
          report["coverage"]["answered"] >= 2 and any(score for score in report["scores"].values() if score), str(report["scores"]))  # fmt: skip
    built = rows[0].get("checklist") or []
    check("AI outage: checklist still built by code", any(row["ok"] for row in built), " ".join(row["label"] for row in built if row["ok"]))


if __name__ == "__main__":
    if OUTAGE:
        runOutageCheck()
    else:
        runOrderChecks()
        runAnswerChecks()
        runParallelChecks()
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f" — FAILED: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)
