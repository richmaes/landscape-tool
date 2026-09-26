"""One place that knows which renderer writes which file: by render mode
(`flat` from M5, `art` from M6) and output extension. The CLI, export
recipes and the editor all dispatch through here, so they can't disagree
about what a mode or format supports.

Mode `3d` (M11) is the scene from a camera: options `camera` (a camera id,
default the scene's first), `width`/`height` in pixels, `surround`; the
plan-only options below don't apply to it.

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

MODES = ("flat", "art", "3d")
# the only options a 3D view uses; the plan's legend, scale and DPI don't apply
_3D_OPTIONS = ("camera", "width", "height", "surround")
EXTENSIONS = (".png", ".svg", ".pdf")

_RENDERERS = {
    ("flat", ".png"): render_scene_to_png,
    ("flat", ".svg"): render_scene_to_svg,
    ("flat", ".pdf"): render_scene_to_pdf,
    ("art", ".png"): render_art_to_png,
    ("art", ".svg"): render_art_to_svg,
    ("art", ".pdf"): render_art_to_pdf,
}


def _render_3d(doc, scene, materials, path, **options):
    from .render3d import render_3d_to_file

    render_3d_to_file(doc, scene, materials, path, **{k: v for k, v in options.items() if k in _3D_OPTIONS})


for _ext in EXTENSIONS:
    _RENDERERS[("3d", _ext)] = _render_3d


def check_output(path: str | Path, mode: str = "flat") -> None:
    """Raise ValueError if nothing can write `path` in `mode`."""
    if mode not in MODES:
        raise ValueError(f"unknown render mode '{mode}' (use 'flat', 'art' or '3d')")
    suffix = Path(path).suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError(f"unsupported output type '{Path(path).suffix}' (use .png, .svg, or .pdf)")


def takes_dpi(path: str | Path, mode: str = "flat") -> bool:
    """Flat SVG/PDF are pure vector, and a 3D view is sized in pixels
    instead; flat PNG and every art format have a DPI."""
    if mode == "3d":
        return False
    return mode == "art" or Path(path).suffix.lower() == ".png"


def render_to_file(doc, scene, materials, path: str | Path, mode: str = "flat", **options: Any) -> None:
    check_output(path, mode)
    if not takes_dpi(path, mode):
        options.pop("dpi", None)
    if mode != "art":
        options.pop("style", None)
    _RENDERERS[(mode, Path(path).suffix.lower())](doc, scene, materials, path, **options)
