"""Test-only loopback worker process with a deterministic checkpoint-free analyzer."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .test_worker_api import FakeChangeAnalyzer
from ..worker_api import WorkerConfig, WorkerState, create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--state", required=True, choices=("starting", "ready", "failed"))
    args = parser.parse_args()
    state = WorkerState(
        WorkerConfig(
            input_root=args.input_root,
            output_root=args.output_root,
            checkpoint=args.output_root / "fake-checkpoint.pth",
            device="cpu",
        )
    )
    if args.state == "ready":
        state.mark_ready(
            FakeChangeAnalyzer(),
            model_name="Change-Agent MCI",
            checkpoint_sha256="a" * 64,
            vocab_size=468,
        )
    elif args.state == "failed":
        state.mark_failed()
    uvicorn.run(create_app(state), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
