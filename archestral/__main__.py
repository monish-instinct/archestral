"""Command line entry point: ``python -m archestral <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import webbrowser
from pathlib import Path


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def cmd_serve(args) -> int:
    from aiohttp import web

    from .server import create_app

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        logging.warning("Binding to %s exposes the service beyond this machine.", args.host)
    app = create_app(Path(args.data_dir) if args.data_dir else None)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}/"
    print(f"\n  Archestral is running at {url}\n  Press Ctrl+C to stop.\n", flush=True)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    web.run_app(app, host=args.host, port=args.port, print=None)
    return 0


def cmd_analyze(args) -> int:
    from .analysis.config import AnalysisConfig
    from .analysis.patterns import load_patterns
    from .analysis.session import analyze_samples
    from .fixtures import fixture_samples, load_fixture

    doc = load_fixture(Path(args.file))
    cfg = AnalysisConfig(target_bpm=args.target_bpm)
    pattern = load_patterns()[args.pattern]
    summary = analyze_samples(fixture_samples(doc), cfg, pattern)
    if not args.beats:
        summary.pop("beats", None)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_gen_fixtures(_args) -> int:
    from .analysis.patterns import BUILTIN_SPECS, PATTERN_DIR, builtin_pattern
    from .fixtures import write_fixtures

    for p in write_fixtures():
        print("wrote", p)
    PATTERN_DIR.mkdir(exist_ok=True)
    for pid in BUILTIN_SPECS:
        path = PATTERN_DIR / f"{pid}.json"
        path.write_text(json.dumps(builtin_pattern(pid).to_dict(), indent=1), encoding="utf-8")
        print("wrote", path)
    return 0


def cmd_diagnose(args) -> int:
    import platform

    from .tracking.webcam import vision_available
    print("python   ", sys.version.split()[0], platform.platform())
    try:
        import numpy
        print("numpy    ", numpy.__version__)
    except ImportError:
        print("numpy     MISSING")
    try:
        import aiohttp
        print("aiohttp  ", aiohttp.__version__)
    except ImportError:
        print("aiohttp   MISSING")
    ok, msg = vision_available()
    print("vision   ", "OK" if ok else "UNAVAILABLE", "-", msg)
    if args.camera is not None and ok:
        import cv2
        cap = cv2.VideoCapture(args.camera)
        opened = cap.isOpened()
        got = cap.read()[0] if opened else False
        cap.release()
        print(f"camera {args.camera}  opened={opened} frame={got}")
        if not opened:
            print("  macOS: grant camera access to your terminal app in System Settings > Privacy & Security > Camera")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archestral", description="Archestral - Adaptive Orchestral Sandbox")
    ap.add_argument("--log-level", default="INFO")
    sub = ap.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="start the local app (default)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--data-dir", default=None)
    s.add_argument("--no-browser", action="store_true")

    a = sub.add_parser("analyze", help="analyze a recorded trajectory JSON file")
    a.add_argument("file")
    a.add_argument("--pattern", default="4-4")
    a.add_argument("--target-bpm", type=float, default=90.0)
    a.add_argument("--beats", action="store_true", help="include individual beat events")

    sub.add_parser("gen-fixtures", help="regenerate synthetic fixtures and pattern files")

    d = sub.add_parser("diagnose", help="check dependencies (and optionally a camera)")
    d.add_argument("--camera", type=int, default=None)

    args = ap.parse_args(argv)
    _setup_logging(args.log_level)
    if args.command is None:
        args = ap.parse_args(["serve", *(argv or sys.argv[1:])])
    return {"serve": cmd_serve, "analyze": cmd_analyze, "gen-fixtures": cmd_gen_fixtures,
            "diagnose": cmd_diagnose}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
