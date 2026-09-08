"""Test-only production worker process for the frozen LEVIR PNG regression fixture."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from ..worker_api import (
    ImagePolicy,
    WorkerConfig,
    create_app,
    initialize_production_state,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--device", required=True)
    args = parser.parse_args()
    config = WorkerConfig(
        input_root=args.input_root,
        output_root=args.output_root,
        checkpoint=args.checkpoint,
        device=args.device,
        host=args.host,
        port=args.port,
    )
    state = initialize_production_state(config)
    uvicorn.run(
        create_app(state, image_policy=ImagePolicy.INTERNAL_LEVIR_PNG_REGRESSION),
        host=config.host,
        port=config.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
