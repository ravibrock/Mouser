"""
Simple command-line interface for exporting and loading Mouser configs.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path
from typing import Any

import yaml

from core.config import (
    DEFAULT_CONFIG,
    _merge_defaults,
    _migrate,
    _validate_types,
    load_config,
    save_config,
)
from core.log_setup import setup_logging


def normalize_config(raw_cfg: Any) -> dict[str, Any]:
    """Return a migrated, default-filled config dict."""
    if not isinstance(raw_cfg, dict):
        raise ValueError("Config JSON must be an object")
    cfg = json.loads(json.dumps(raw_cfg))
    cfg = _migrate(cfg)
    cfg = _merge_defaults(cfg, DEFAULT_CONFIG)
    cfg = _validate_types(cfg, DEFAULT_CONFIG)
    return cfg


def export_config(*, stdout=None) -> int:
    stdout = stdout or sys.stdout
    json.dump(load_config(), stdout, indent=2)
    stdout.write("\n")
    return 0


def _read_config_json(path: str, ft: str=None) -> dict[str, Any]:
    if path == "-":
        raw = sys.stdin
    else:
        with open(path, "r", encoding="utf-8") as f:
            raw = f

    ft = ft or (Path(path).suffix.lower().lstrip(".") if path != "-" else "json")

    # load path into json
    if ft == "json":
        processed = json.load(raw)
    elif ft == "yaml":
        processed = yaml.safe_load(raw)
    else:
        raise ValueError(f"Unsupported config file type: {ft}")

    return normalize_config(processed)


def run_headless_instance(*, stop_event: threading.Event | None = None, engine_factory=None) -> int:
    if engine_factory is None:
        from core.engine import Engine

        engine_factory = Engine

    stop_event = stop_event or threading.Event()
    engine = engine_factory()

    def _request_stop(_signum, _frame):
        stop_event.set()

    previous_handlers: list[tuple[int, Any]] = []
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            previous_handlers.append((sig, signal.getsignal(sig)))
            signal.signal(sig, _request_stop)
        except (AttributeError, ValueError):
            continue

    try:
        engine.start()
        while not stop_event.wait(0.5):
            pass
        return 0
    finally:
        engine.stop()
        for sig, previous in previous_handlers:
            try:
                signal.signal(sig, previous)
            except (AttributeError, ValueError):
                pass


def load_config_and_start(path: str, *, stop_event: threading.Event | None = None, engine_factory=None) -> int:
    cfg = _read_config_json(path)
    save_config(cfg)
    return run_headless_instance(stop_event=stop_event, engine_factory=engine_factory)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mouser command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "export",
        help="Print the current Mouser config as JSON",
    )

    load_parser = subparsers.add_parser(
        "load",
        help="Load a JSON config and start Mouser headlessly",
    )

    load_parser.add_argument(
        "config",
        help="Path to a Mouser config JSON file, or '-' to read from stdin",
    )
    load_parser.add_argument(
        "-t",
        "--filetype",
        choices=["json", "yaml"],
        help="Override config file type detection",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "export":
        return export_config()
    if args.command == "load":
        setup_logging()
        return load_config_and_start(args.config)
    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
