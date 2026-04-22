"""Filesystem layout and artifact names shared across services.

Paths here are names or segments relative to well-known roots
(`DATA_DIR` / task id, `SIM_PROJECT_DIR`, or a task `output_dir`).
"""

from __future__ import annotations

from pathlib import Path

# Task workspace: DATA_DIR / <task_id> / …
TASK_OUTPUT_SUBDIR = "output"
TASK_CONFIG_FILENAME = "config.conf"
TASK_LAUNCH_PARAMS_FILENAME = "launch-params.json"

# Under SIM_PROJECT_DIR (search first match)
SIM_DEFAULT_CONFIG_RELATIVE_PATHS: tuple[Path, ...] = (
    Path("config") / "simulation.conf",
    Path("simulation.conf"),
)

# Under each task's output directory (first existing wins)
METRICS_JSONL_FILENAMES: tuple[str, ...] = (
    "simulation_metrics.jsonl",
    "metrics.jsonl",
)


def metrics_jsonl_paths(output_dir: Path) -> tuple[Path, ...]:
    return tuple(output_dir / name for name in METRICS_JSONL_FILENAMES)
