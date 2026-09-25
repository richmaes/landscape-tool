"""Export recipes (M7 batch export): several outputs of one scene, in one run.

A recipe is a small YAML file::

    scene: ../scenes/backyard.yaml       # required
    materials: ../assets/materials.yaml  # optional
    defaults:                            # optional; applied to every output
      legend: true
    outputs:                             # required, at least one
      - out: ../out/plan.pdf
        scale_bar: true
        north_arrow: true
      - out: ../out/plan.png
        dpi: 300

Paths are relative to the recipe file itself, so a recipe works wherever
it's run from (`materials`, if omitted, falls back to
`assets/materials.yaml` in the working directory, like `landscape render`).
Each output takes the same options as `landscape render`: `mode` (`flat`
or `art`), `dpi` (flat PNG, or any art output — a `dpi` in `defaults`
simply doesn't apply to flat SVG/PDF outputs), `legend`, `annotations`,
`scale_bar`, `north_arrow`, `north_angle`, and for art mode `wash`
(`diffuse` or `layered`) and `paper_image` (a scan, relative to the recipe).

The whole recipe is validated before anything is rendered, so a typo in
the last output never leaves a half-finished batch behind; errors name the
recipe file and line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .geometry import resolve_scene
from .materials import load_materials
from .render import EXTENSIONS, render_to_file, takes_dpi
from .scene_io import line_of, load_raw, load_scene

_WASHES = ("diffuse", "layered")
_TOP_LEVEL_KEYS = {"scene", "materials", "defaults", "outputs"}
_BOOL_OPTIONS = {
    "legend": "show_legend",
    "annotations": "show_annotations",
    "scale_bar": "scale_bar",
    "north_arrow": "north_arrow",
}
_NUMBER_OPTIONS = {"dpi": "dpi", "north_angle": "north_deg"}
_ART_KEYS = {"wash", "paper_image"}
_OUTPUT_KEYS = {"out", "mode"} | set(_BOOL_OPTIONS) | set(_NUMBER_OPTIONS) | _ART_KEYS


class RecipeError(ValueError):
    """A problem in an export recipe, located by file and line."""


@dataclass
class OutputSpec:
    path: Path
    mode: str = "flat"
    render_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Recipe:
    scene_path: Path
    materials_path: Path
    outputs: list[OutputSpec]


def _relative_to(base: Path, value: Any) -> Path:
    """`value` resolved against the recipe's folder, tidied (no `a/../b`)
    but not made absolute, so printed paths stay short."""
    return Path(os.path.normpath(base / str(value)))


def load_recipe(path: str | Path) -> Recipe:
    path = Path(path)
    raw = load_raw(path) or {}
    base = path.parent

    def error(node: Any, message: str) -> RecipeError:
        line = line_of(node)
        where = f"{path.name}, line {line}" if line else path.name
        return RecipeError(f"{where}: {message}")

    if not isinstance(raw, dict):
        raise error(raw, "a recipe must be a mapping with 'scene' and 'outputs'")
    for key in raw:
        if key not in _TOP_LEVEL_KEYS:
            raise error(raw, f"unknown top-level key '{key}' (expected: {', '.join(sorted(_TOP_LEVEL_KEYS))})")
    if not raw.get("scene"):
        raise error(raw, "'scene' is required")
    scene_path = _relative_to(base, raw["scene"])
    materials_path = _relative_to(base, raw["materials"]) if raw.get("materials") else Path("assets/materials.yaml")

    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise error(raw, "'defaults' must be a mapping of output options")
    for key in defaults:
        if key not in _OUTPUT_KEYS - {"out"}:
            raise error(defaults, f"unknown option '{key}' in defaults")
    outputs_raw = raw.get("outputs") or []
    if not outputs_raw:
        raise error(raw, "a recipe needs at least one output under 'outputs'")

    outputs = [_parse_output(entry, defaults, base, error) for entry in outputs_raw]
    return Recipe(scene_path=scene_path, materials_path=materials_path, outputs=outputs)


def _parse_output(entry: Any, defaults: dict, base: Path, error) -> OutputSpec:
    if not isinstance(entry, dict):
        raise error(entry, "each output must be a mapping with at least 'out'")
    for key in entry:
        if key not in _OUTPUT_KEYS:
            raise error(entry, f"unknown option '{key}' (expected: {', '.join(sorted(_OUTPUT_KEYS))})")
    if not entry.get("out"):
        raise error(entry, "'out' is required")

    out = _relative_to(base, entry["out"])
    if out.suffix.lower() not in EXTENSIONS:
        raise error(entry, f"unsupported output type '{out.suffix}' (use .png, .svg, or .pdf)")

    options = {**defaults, **entry}
    mode = options.get("mode", "flat")
    if mode not in ("flat", "art"):
        raise error(entry, f"mode must be 'flat' or 'art', not '{mode}'")
    if "dpi" in entry and not takes_dpi(out, mode):
        raise error(entry, "dpi only applies to .png outputs in flat mode (flat SVG and PDF are vector)")
    for key in _ART_KEYS & set(entry):
        if mode != "art":
            raise error(entry, f"{key} only applies to mode: art")

    kwargs: dict[str, Any] = {}
    for key, kwarg in _BOOL_OPTIONS.items():
        if key in options:
            if not isinstance(options[key], bool):
                raise error(entry, f"{key} must be true or false, not '{options[key]}'")
            kwargs[kwarg] = options[key]
    for key, kwarg in _NUMBER_OPTIONS.items():
        if key in options:
            value = options[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise error(entry, f"{key} must be a number, not '{value}'")
            if key == "dpi" and not takes_dpi(out, mode):
                continue  # a default dpi is for rasters; flat vector outputs ignore it
            kwargs[kwarg] = float(value)
    if mode == "art":
        from .render_art import ArtStyle

        wash = options.get("wash", "diffuse")
        if wash not in _WASHES:
            raise error(entry, f"wash must be one of {', '.join(_WASHES)}, not '{wash}'")
        paper = options.get("paper_image")
        kwargs["style"] = ArtStyle(wash=wash, paper_image=str(_relative_to(base, paper)) if paper else None)
    return OutputSpec(path=out, mode=mode, render_kwargs=kwargs)


def run_recipe(recipe: Recipe) -> list[Path]:
    """Resolve the scene once and render every output. Returns the paths
    written, in recipe order."""
    doc = load_scene(recipe.scene_path)
    scene = resolve_scene(doc)
    materials = load_materials(recipe.materials_path)
    written = []
    for output in recipe.outputs:
        output.path.parent.mkdir(parents=True, exist_ok=True)
        render_to_file(doc, scene, materials, output.path, mode=output.mode, **output.render_kwargs)
        written.append(output.path)
    return written
