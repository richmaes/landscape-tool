"""CLI entry point: `landscape render scene.yaml --mode flat --out out/plan.png`

Developer back door per the project decisions in TODO.md; the graphical
editor (M8) is the primary interface. Rendering itself lands with M2/M3/M5 —
this skeleton only wires up argument parsing so the command exists early.
"""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="landscape")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="Render a scene file to an image")
    render.add_argument("scene", help="Path to a scene YAML file")
    render.add_argument(
        "--mode",
        choices=["flat", "art"],
        default="flat",
        help="Render mode: flat pastel color-coding or hand-drawn pastel art",
    )
    render.add_argument("--out", required=True, help="Output file path")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "render":
        parser.exit(
            1,
            "landscape render: not yet implemented (scene schema and geometry "
            "engine land in M2/M3)\n",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
