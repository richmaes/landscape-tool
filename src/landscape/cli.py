"""CLI entry point: `landscape render scene.yaml --mode flat --out out/plan.png`

Developer back door per the project decisions in TODO.md; the graphical
editor (M8) is the primary interface. `--mode flat` is the M5 flat pastel
render; `--mode art` is M6's watercolor-and-pencil painting.

Run from the repo root: `--materials` defaults to `assets/materials.yaml`,
resolved relative to the current directory, not installed as package data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .geometry import resolve_scene
from .materials import load_materials
from .render import check_output, render_to_file
from .scene_io import load_scene


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="landscape")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="Render a scene file to an image")
    render.add_argument("scene", help="Path to a scene YAML file")
    render.add_argument(
        "--mode",
        choices=["flat", "art"],
        default="flat",
        help="Render mode: flat pastel color-coding or hand-drawn watercolor-and-pencil art",
    )
    render.add_argument(
        "--wash", choices=["diffuse", "layered"], default="diffuse", help="Art mode: watercolor wash technique"
    )
    render.add_argument("--paper-image", default=None, help="Art mode: a paper scan to paint on (PNG/JPEG)")
    render.add_argument("--out", required=True, help="Output file path (.svg, .pdf, or .png)")
    render.add_argument(
        "--materials", default="assets/materials.yaml", help="Path to a material library YAML file"
    )
    render.add_argument("--legend", action="store_true", help="Draw a material legend")
    render.add_argument(
        "--show-annotations", action="store_true", help="Draw annotation objects (technical view)"
    )
    render.add_argument("--scale-bar", action="store_true", help="Add a scale bar in a strip below the drawing")
    render.add_argument("--north-arrow", action="store_true", help="Add a north arrow in a strip below the drawing")
    render.add_argument(
        "--north-angle",
        type=float,
        default=0.0,
        help="Degrees clockwise from page-up that north lies at (default 0: page-up is north)",
    )
    render.add_argument(
        "--dpi",
        type=float,
        default=None,
        help="Pixels per inch of the drawing's print size (the scene's own scale), recorded in PNGs so they "
        "print at that size. Flat mode: PNG only, default 72. Art mode: every format (it's the painting's "
        "resolution, embedded in SVG/PDF), default 200",
    )

    export = subparsers.add_parser(
        "export", help="Render every output listed in an export recipe (see landscape/export_recipe.py)"
    )
    export.add_argument("recipe", help="Path to an export recipe YAML file")

    edit = subparsers.add_parser("edit", help="Open a scene in the graphical editor (M8)")
    edit.add_argument("scene", help="Path to a scene YAML file")
    edit.add_argument(
        "--materials", default="assets/materials.yaml", help="Path to a material library YAML file"
    )
    edit.add_argument(
        "--show-annotations", action="store_true", help="Show annotation objects (technical view)"
    )
    edit.add_argument(
        "--rules", default=None, help="Path to a rules YAML file for live rule-checker feedback"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "render":
        out_path = Path(args.out)
        try:
            check_output(out_path, args.mode)
        except ValueError as exc:
            parser.exit(1, f"landscape render: {exc}\n")

        doc = load_scene(args.scene)
        scene = resolve_scene(doc)
        materials = load_materials(args.materials)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        kwargs = {
            "show_legend": args.legend,
            "show_annotations": args.show_annotations,
            "scale_bar": args.scale_bar,
            "north_arrow": args.north_arrow,
            "north_deg": args.north_angle,
        }
        if args.dpi is not None:
            kwargs["dpi"] = args.dpi
        if args.mode == "art":
            from .render_art import ArtStyle

            kwargs["style"] = ArtStyle(wash=args.wash, paper_image=args.paper_image)
        render_to_file(doc, scene, materials, out_path, mode=args.mode, **kwargs)
        print(f"landscape render: wrote {out_path}")

    elif args.command == "export":
        from .export_recipe import RecipeError, load_recipe, run_recipe

        try:
            recipe = load_recipe(args.recipe)
        except RecipeError as exc:
            parser.exit(1, f"landscape export: {exc}\n")
        for path in run_recipe(recipe):
            print(f"landscape export: wrote {path}")

    elif args.command == "edit":
        from PySide6.QtWidgets import QApplication

        from .editor import EditorWindow

        app = QApplication.instance() or QApplication(sys.argv[:1])
        window = EditorWindow(materials_path=args.materials, rules_path=args.rules)
        window.load_scene(args.scene, show_annotations=args.show_annotations)
        window.show()
        return app.exec()

    return 0


if __name__ == "__main__":
    sys.exit(main())
