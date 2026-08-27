#!/usr/bin/env python3
"""Locally drive the async stage chain without Pub/Sub.

Walks monitor -> research -> script -> render -> publish -> analyst by calling
colonyv_agent.stages.run_stage directly, mirroring exactly what the Pub/Sub
worker would do per message. Used to validate sequencing and gate behaviour
before wiring live topics/subscriptions.

Usage:
    GOOGLE_CLOUD_PROJECT=<project> GOOGLE_CLOUD_LOCATION=global \
        .venv/bin/python3 scripts/run_stage_chain.py [--stories N] [--out DIR]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from colonyv_agent import pipeline_runtime, stages  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stories", type=int, default=1)
    parser.add_argument("--out", default=str(PROJECT_ROOT / "output"))
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out)
    pipeline_runtime.configure(
        out_dir=out_dir, run=run_id, skip=True
    )
    print(f"run_id={run_id} out_dir={out_dir} stories={args.stories}")

    state: dict = {"stories_target": args.stories, "run_id": run_id}
    queue = [("monitor", 0, 1)]
    decisions = []

    while queue:
        stage, story_index, attempt = queue.pop(0)
        result = stages.run_stage(state, stage, story_index, attempt)
        state = result["state"]
        decisions.append((stage, story_index, attempt, result["decision"]))
        print(f"[{stage}] decision={result['decision']} "
              f"next={[(s, i, a) for s, i, a in result.get('next', [])]}")
        for nxt in result.get("next", []):
            queue.append(nxt)
        if not result.get("next"):
            break

    print("\n=== chain summary ===")
    for stage, idx, attempt, decision in decisions:
        print(f"  {stage:8s} story={idx} attempt={attempt} -> {decision}")
    terminal = decisions[-1] if decisions else None
    ok = terminal and terminal[1] in {"complete", "failed", "blocked"} and any(
        d[0] == "render" and d[3] == "continue" for d in decisions
    )
    print("RESULT:", "OK" if ok else "CHECK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())