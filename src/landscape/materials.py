"""Material system (M4).

A material maps an object's `material:` string (the scene schema, M2) to
render parameters: a flat pastel color for M5, plus a texture recipe and
edge treatment for M6's hand-drawn mode. M6 hasn't picked its texture
techniques yet, so `texture` here is just a free-form name + params bag,
not consumed by any renderer yet.

Kept in its own library file (`assets/materials.yaml`), separate from
scenes, so a palette can be swapped without touching any scene YAML.
"""

from __future__ import annotations

from colorsys import rgb_to_hls
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from ruamel.yaml import YAML

_yaml = YAML(typ="safe")

FALLBACK_COLOR = "#FF00FF"  # unmistakably a bug, never a real material


class MaterialError(Exception):
    pass


@dataclass
class Material:
    id: str
    name: str
    color: str  # "#RRGGBB"
    texture: dict[str, Any] = field(default_factory=dict)
    edge: dict[str, Any] = field(default_factory=lambda: {"weight": 1.0, "color": None})


_FALLBACK = Material(id="__fallback__", name="Missing material", color=FALLBACK_COLOR)


@dataclass
class MaterialLibrary:
    materials: dict[str, Material]

    def resolve(self, material_id: str | None) -> Material:
        """Object to material to render parameters, with a sensible
        fallback: an unmistakable color rather than a crash or a silent
        blank, so a typo'd or not-yet-defined material is obvious in a
        render instead of hidden."""
        if material_id is None:
            return _FALLBACK
        return self.materials.get(material_id, _FALLBACK)


def load_materials(path: str | Path) -> MaterialLibrary:
    with open(path, "r", encoding="utf-8") as f:
        data = _yaml.load(f) or {}
    materials = {}
    for mat_id, mat_data in (data.get("materials") or {}).items():
        if "color" not in mat_data:
            raise MaterialError(f"material '{mat_id}' is missing a 'color'")
        materials[mat_id] = Material(
            id=mat_id,
            name=mat_data.get("name", mat_id.replace("_", " ").title()),
            color=mat_data["color"],
            texture=mat_data.get("texture", {}),
            edge=mat_data.get("edge", {"weight": 1.0, "color": None}),
        )
    return MaterialLibrary(materials=materials)


def render_swatch(material: Material, size: int = 32) -> Image.Image:
    """A flat-color preview swatch for the editor's material picker (M8):
    "the designer chooses materials by appearance and name, never by hex
    code." Texture is M6's job; this is deliberately just the flat color."""
    return Image.new("RGB", (size, size), _hex_to_rgb(material.color))


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise MaterialError(f"expected a 6-digit hex color, got '{hex_color}'")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def color_distance(a: str, b: str) -> float:
    """A perceptual-ish distance between two hex colors in HSL space, with
    hue weighted higher: for a low-saturation pastel palette, hue is
    mostly what keeps two swatches telling apart, since lightness and
    saturation are already compressed into a narrow pastel range."""
    ra, ga, ba = (c / 255 for c in _hex_to_rgb(a))
    rb, gb, bb = (c / 255 for c in _hex_to_rgb(b))
    ha, la, sa = rgb_to_hls(ra, ga, ba)
    hb, lb, sb = rgb_to_hls(rb, gb, bb)
    dh = min(abs(ha - hb), 1 - abs(ha - hb))  # hue is circular
    return ((dh * 3) ** 2 + (la - lb) ** 2 + (sa - sb) ** 2) ** 0.5


def find_indistinguishable_pairs(
    library: MaterialLibrary, min_distance: float = 0.12
) -> list[tuple[str, str, float]]:
    """Pairs of materials whose colors are close enough to risk being
    confused sitting next to each other in a render. A palette-authoring
    check, not a scene constraint — same warn-don't-block spirit as M3b,
    just at a different point in the workflow."""
    ids = list(library.materials)
    close = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            d = color_distance(library.materials[a].color, library.materials[b].color)
            if d < min_distance:
                close.append((a, b, d))
    return close
