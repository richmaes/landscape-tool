"""One place that knows which renderer writes which file: by render mode
(`flat` from M5, `art` from M6) and output extension. The CLI, export
recipes and the editor all dispatch through here, so they can't disagree
about what a mode or format supports.

Options every renderer takes: `show_legend` and `scale_indicator` (the
drawing's own legend box and scale line, at their saved positions),
`show_annotations`, and `scale_bar` / `north_arrow` / `north_deg` (the strip
below the drawing). Flat PNG and every art format
also take `dpi` (for art it's the painting's resolution, embedded in
PDF/SVG). Art also takes `style` (an `ArtStyle`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .render_art import render_art_to_pdf, render_art_to_png, render_art_to_svg
from .render_flat import render_scene_to_pdf, render_scene_to_png, render_scene_to_svg

MODES = ("flat", "art")
EXTENSIONS = (".png", ".svg", ".pdf")

_RENDERERS = {
    ("flat", ".png"): render_scene_to_png,
    ("flat", ".svg"): render_scene_to_svg,
    ("flat", ".pdf"): render_scene_to_pdf,
    ("art", ".png"): render_art_to_png,
    ("art", ".svg"): render_art_to_svg,
    ("art", ".pdf"): render_art_to_pdf,
}


def check_output(path: str | Path, mode: str = "flat") -> None:
    """Raise ValueError if nothing can write `path` in `mode`."""
    if mode not in MODES:
        raise ValueError(f"unknown render mode '{mode}' (use 'flat' or 'art')")
    suffix = Path(path).suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError(f"unsupported output type '{Path(path).suffix}' (use .png, .svg, or .pdf)")


def takes_dpi(path: str | Path, mode: str = "flat") -> bool:
    """Flat SVG/PDF are pure vector; everything else has a resolution."""
    return mode == "art" or Path(path).suffix.lower() == ".png"


def render_to_file(doc, scene, materials, path: str | Path, mode: str = "flat", **options: Any) -> None:
    check_output(path, mode)
    if not takes_dpi(path, mode):
        options.pop("dpi", None)
    if mode != "art":
        options.pop("style", None)
    _RENDERERS[(mode, Path(path).suffix.lower())](doc, scene, materials, path, **options)
