"""Command-line entry point for the local-only Tool 2 MCI worker."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import uvicorn

from .worker_api import WorkerConfig, create_app, initialize_production_state


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local SatQuery MCI worker.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8012, type=int)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--device", default="cuda:0")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    config = WorkerConfig(
        input_root=args.input_root,
        output_root=args.output_root,
        checkpoint=args.checkpoint,
        device=args.device,
        host=args.host,
        port=args.port,
    )
    state = initialize_production_state(config)
    uvicorn.run(create_app(state), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
