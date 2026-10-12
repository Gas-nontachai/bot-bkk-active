"""Counts and elapsed times for debugging and comparing booking runs."""
from collections import defaultdict
from datetime import datetime
import json
import time
from zoneinfo import ZoneInfo


class RunMetrics:
    def __init__(self):
        self.started = time.perf_counter()
        self.started_at = datetime.now(ZoneInfo("Asia/Bangkok")).isoformat()
        self.counts = defaultdict(int)
        self.seconds = defaultdict(float)
        self.steps = []

    def record(self, category, elapsed):
        self.counts[category] += 1
        self.seconds[category] += elapsed

    def record_step(self, name, elapsed, outcome, attempt):
        self.steps.append({"name": name, "seconds": round(elapsed, 4),
                           "outcome": outcome, "attempt": attempt})

    def finish(self, folder, *, outcome, attempts, capture_mode):
        averages = {key: round(value / self.counts[key], 4)
                    for key, value in self.seconds.items() if self.counts[key]}
        report = {"started_at": self.started_at,
                  "finished_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
                  "total_seconds": round(time.perf_counter() - self.started, 4),
                  "outcome": outcome, "attempts": attempts, "capture_mode": capture_mode,
                  "png_files": len(list((folder / "screenshots").glob("*.png"))),
                  "ui_files": len(list((folder / "ui").glob("*.xml"))),
                  "counts": dict(self.counts),
                  "operation_seconds": {key: round(value, 4) for key, value in self.seconds.items()},
                  "operation_average_seconds": averages,
                  "steps": self.steps,
                  "slowest_steps": sorted(self.steps, key=lambda step: step["seconds"], reverse=True)[:5],
                  "timing_note": "Step durations include nested steps; UI reads include ADB time. Do not add overlapping durations."}
        (folder / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
