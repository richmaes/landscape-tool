"""CLI entry point: `landscape render scene.yaml --mode flat --out out/plan.png`

Developer back door per the project decisions in TODO.md; the graphical
editor (M8) is the primary interface. `--mode flat` is the M5 end-to-end
path: load, resolve, render. `--mode art` still stubs out since M6 hasn't
picked its texture techniques yet.

Run from the repo root: `--materials` defaults to `assets/materials.yaml`,
resolved relative to the current directory, not installed as package data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .geometry import resolve_scene
from .materials import load_materials
from .render_flat import render_scene_to_pdf, render_scene_to_png, render_scene_to_svg
from .scene_io import load_scene

_RENDERERS = {
    ".svg": render_scene_to_svg,
    ".pdf": render_scene_to_pdf,
    ".png": render_scene_to_png,
}


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
    render.add_argument("--out", required=True, help="Output file path (.svg, .pdf, or .png)")
    render.add_argument(
        "--materials", default="assets/materials.yaml", help="Path to a material library YAML file"
    )
    render.add_argument("--legend", action="store_true", help="Draw a material legend")
    render.add_argument(
        "--show-annotations", action="store_true", help="Draw annotation objects (technical view)"
    )
    render.add_argument("--dpi-scale", type=float, default=1.0, help="PNG-only resolution multiplier")

    edit = subparsers.add_parser("edit", help="Open a scene in the graphical editor (M8)")
    edit.add_argument("scene", help="Path to a scene YAML file")
    edit.add_argument(
        "--materials", default="assets/materials.yaml", help="Path to a material library YAML file"
    )
    edit.add_argument(
        "--show-annotations", action="store_true", help="Show annotation objects (technical view)"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "render":
        if args.mode == "art":
            parser.exit(
                1,
                "landscape render --mode art: not yet implemented "
                "(M6 hasn't picked its texture techniques yet)\n",
            )

        out_path = Path(args.out)
        renderer = _RENDERERS.get(out_path.suffix.lower())
        if renderer is None:
            parser.exit(1, f"landscape render: unsupported --out extension '{out_path.suffix}' (use .svg, .pdf, or .png)\n")

        doc = load_scene(args.scene)
        scene = resolve_scene(doc)
        materials = load_materials(args.materials)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        kwargs = {"show_legend": args.legend, "show_annotations": args.show_annotations}
        if renderer is render_scene_to_png:
            kwargs["dpi_scale"] = args.dpi_scale
        renderer(doc, scene, materials, out_path, **kwargs)
        print(f"landscape render: wrote {out_path}")

    elif args.command == "edit":
        from PySide6.QtWidgets import QApplication

        from .editor import EditorWindow

        app = QApplication.instance() or QApplication(sys.argv[:1])
        window = EditorWindow(materials_path=args.materials)
        window.load_scene(args.scene, show_annotations=args.show_annotations)
        window.show()
        return app.exec()

    return 0


if __name__ == "__main__":
    sys.exit(main())
