"""Scene document object model (M2).

A scene is data, not code: every object here is a plain dataclass that
round-trips losslessly through `scene_io` (backed by `ruamel.yaml`) so the
future graphical editor (M8) can load, edit, and save a scene file without
disturbing anything it didn't touch.

Relations (`center_of`, `mirror_of`, `relative_to`, `chord_of`) are a closed
vocabulary, not an expression language — each one must map to a simple GUI
control. Resolving them into concrete geometry happens in M3; this module
only defines their shape and validates references.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SchemaError(Exception):
    """A scene document is malformed. Carries a scene-relative location when
    the source mapping has line/column info (see `scene_io.line_of`)."""

    def __init__(self, message: str, path: str = "", line: int | None = None):
        self.path = path
        self.line = line
        location = f"{path}" if path else "<document>"
        if line is not None:
            location += f" (line {line})"
        super().__init__(f"{location}: {message}")


# ---------------------------------------------------------------------------
# Relations — closed vocabulary, resolved in M3
# ---------------------------------------------------------------------------


@dataclass
class CenterOf:
    """Center this object on another object's center. e.g. a keep-out circle
    centred on its firepit."""

    ref: str


@dataclass
class MirrorOf:
    """Mirror this object from another object about an axis through a point.
    `about_x` mirrors across a vertical line at that x (left/right deck
    pairs); `about_y` mirrors across a horizontal line at that y."""

    ref: str
    about_x: float | None = None
    about_y: float | None = None

    def __post_init__(self) -> None:
        if (self.about_x is None) == (self.about_y is None):
            raise SchemaError(
                "mirror_of requires exactly one of about_x or about_y"
            )


@dataclass
class RelativeTo:
    """Position this object at a fixed offset from another object's origin."""

    ref: str
    dx: float = 0.0
    dy: float = 0.0


@dataclass
class ChordOf:
    """Derive this line/fence as a chord across a circular object at a given
    signed distance from its center along the normal direction implied by
    `angle_deg` (0 = horizontal chord, offset south is negative)."""

    ref: str
    offset: float
    angle_deg: float = 0.0


@dataclass
class BooleanOp:
    """A boolean relationship declared on an object — e.g. a bed carved out
    of lawn, or a patio cut from decking. `op` says how this object's own
    primitive combines with the primitives of the objects in `targets`.
    Executing the actual geometry boolean is M3's job (see "Boolean ops,
    overlap resolution" there); this only declares the intent."""

    op: str  # "union" | "difference" | "intersection"
    targets: list[str] = field(default_factory=list)

    VALID_OPS: ClassVar[set[str]] = {"union", "difference", "intersection"}

    def __post_init__(self) -> None:
        if self.op not in self.VALID_OPS:
            raise SchemaError(f"boolean op must be one of {sorted(self.VALID_OPS)}, got '{self.op}'")
        if not self.targets:
            raise SchemaError("boolean op requires at least one target object id")


def parse_boolean(data: dict[str, Any] | None) -> BooleanOp | None:
    if not data:
        return None
    return BooleanOp(op=data["op"], targets=list(data.get("targets", [])))


Relation = CenterOf | MirrorOf | RelativeTo | ChordOf

_RELATION_KEYS: dict[str, type] = {
    "center_of": CenterOf,
    "mirror_of": MirrorOf,
    "relative_to": RelativeTo,
    "chord_of": ChordOf,
}


def parse_relation(data: dict[str, Any]) -> Relation | None:
    """Pull a relation out of an object's mapping, if one is present.
    Exactly one relation key may appear on a given object.

    Relations use flat sibling keys, not a nested payload — e.g.
    `mirror_of: deck_west` with a sibling `about_x: 30` — since each one
    must map to a simple GUI control rather than a sub-form."""

    present = [key for key in _RELATION_KEYS if key in data]
    if not present:
        return None
    if len(present) > 1:
        raise SchemaError(f"object has more than one relation: {present}")

    key = present[0]
    ref = data[key]
    if not isinstance(ref, str):
        raise SchemaError(f"{key} must be an object id (string), got {ref!r}")

    if key == "center_of":
        return CenterOf(ref=ref)
    if key == "chord_of":
        if "offset" not in data:
            raise SchemaError("chord_of requires a sibling 'offset'")
        return ChordOf(ref=ref, offset=data["offset"], angle_deg=data.get("angle_deg", 0.0))
    if key == "mirror_of":
        return MirrorOf(ref=ref, about_x=data.get("about_x"), about_y=data.get("about_y"))
    if key == "relative_to":
        return RelativeTo(ref=ref, dx=data.get("dx", 0.0), dy=data.get("dy", 0.0))
    raise AssertionError(f"unhandled relation key: {key}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class Primitive:
    """Base for the parametric primitives listed in TODO.md M2. Subclasses
    are plain dataclasses; `kind` is the YAML `type:` discriminator."""

    kind: ClassVar[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Primitive":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)


@dataclass
class Circle(Primitive):
    kind: ClassVar[str] = "circle"
    cx: float = 0.0
    cy: float = 0.0
    r: float = 0.0


@dataclass
class Ellipse(Primitive):
    kind: ClassVar[str] = "ellipse"
    cx: float = 0.0
    cy: float = 0.0
    rx: float = 0.0
    ry: float = 0.0


@dataclass
class Rect(Primitive):
    kind: ClassVar[str] = "rect"
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    rotation: float = 0.0
    corner_r: float = 0.0


@dataclass
class Polygon(Primitive):
    kind: ClassVar[str] = "polygon"
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class RegularPolygon(Primitive):
    kind: ClassVar[str] = "regular_polygon"
    cx: float = 0.0
    cy: float = 0.0
    sides: int = 6
    size: float = 0.0
    rotation: float = 0.0


@dataclass
class Line(Primitive):
    kind: ClassVar[str] = "line"
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0


@dataclass
class FenceLine(Primitive):
    kind: ClassVar[str] = "fence_line"
    points: list[tuple[float, float]] = field(default_factory=list)
    post_spacing: float = 8.0
    post_size: float = 0.33
    rail_count: int = 2
    height: float = 6.0


@dataclass
class WavyPath(Primitive):
    """Spline through control points, noise-modulated normal offset.
    `waviness` in [0, 1] maps to amplitude; deterministic per `seed`.
    Resolved to geometry in M3 — not used by the current real scene, but
    needed for organic bed edges."""

    kind: ClassVar[str] = "wavy_path"
    points: list[tuple[float, float]] = field(default_factory=list)
    closed: bool = False
    waviness: float = 0.3
    wavelength: float = 2.0
    seed: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.waviness <= 1.0:
            raise SchemaError(f"waviness must be in [0, 1], got {self.waviness}")


@dataclass
class Walkway(Primitive):
    kind: ClassVar[str] = "walkway"
    points: list[tuple[float, float]] = field(default_factory=list)
    width: float = 3.0


@dataclass
class Keepout(Primitive):
    """A zone that carries a rule rather than a material — see M3b. Wraps
    another shape (its own primitive) plus the rule it enforces."""

    kind: ClassVar[str] = "keepout"
    shape: Primitive | None = None
    rule: str = ""


PRIMITIVE_TYPES: dict[str, type[Primitive]] = {
    cls.kind: cls
    for cls in (
        Circle,
        Ellipse,
        Rect,
        Polygon,
        RegularPolygon,
        Line,
        FenceLine,
        WavyPath,
        Walkway,
        Keepout,
    )
}


def parse_primitive(data: dict[str, Any]) -> Primitive:
    type_name = data.get("type")
    cls = PRIMITIVE_TYPES.get(type_name)
    if cls is None:
        raise SchemaError(
            f"unknown primitive type '{type_name}'; expected one of {sorted(PRIMITIVE_TYPES)}"
        )
    if cls is Keepout:
        shape_data = data.get("shape")
        shape = parse_primitive(shape_data) if shape_data else None
        return Keepout(shape=shape, rule=data.get("rule", ""))
    if cls in (Polygon, FenceLine, WavyPath, Walkway):
        payload = dict(data)
        if "points" in payload:
            payload["points"] = [tuple(p) for p in payload["points"]]
        return cls.from_dict(payload)
    return cls.from_dict(data)


def primitive_to_raw_dict(primitive: Primitive) -> dict[str, Any]:
    """The inverse of `parse_primitive`: a plain dict of YAML-ready
    fields (including `type`), for the editor's create-object feature to
    insert into the raw round-trip document. Field names already match
    YAML key names one-to-one (that's what `from_dict` relies on), so
    this only needs to handle the two shapes `parse_primitive` special-
    cases: `points` lists (tuples back to plain lists) and `Keepout`'s
    nested `shape`."""
    data: dict[str, Any] = {"type": primitive.kind}
    for f in fields(primitive):
        value = getattr(primitive, f.name)
        if f.name == "points":
            value = [list(p) for p in value]
        elif isinstance(value, Primitive):
            value = primitive_to_raw_dict(value)
        data[f.name] = value
    return data


# ---------------------------------------------------------------------------
# Object model
# ---------------------------------------------------------------------------


@dataclass
class Transform:
    """An object-level translate/rotate/scale, applied on top of whatever
    the primitive's own fields already describe (e.g. a rect's `rotation`
    is its intrinsic shape orientation; this is the placement on top of
    that). Identity by default. Composing these into a stack, and applying
    them to groups, is M3's job — this is just the declared shape."""

    tx: float = 0.0
    ty: float = 0.0
    rotation: float = 0.0
    scale: float = 1.0


def parse_transform(data: dict[str, Any] | None) -> Transform:
    if not data:
        return Transform()
    known = {f.name for f in fields(Transform)}
    unknown = set(data) - known
    if unknown:
        raise SchemaError(f"unknown transform field(s): {sorted(unknown)}")
    return Transform(**data)


@dataclass
class SceneObject:
    """Every scene object has an id, a type-specific primitive, a material
    reference, a layer/z-order, an object-level transform, and at most one
    relation."""

    id: str
    primitive: Primitive
    material: str | None = None
    layer: str = "default"
    z: int = 0
    annotation: bool = False
    relation: Relation | None = None
    definition: str | None = None  # when instancing a reusable `definitions` entry
    transform: Transform = field(default_factory=Transform)
    boolean: BooleanOp | None = None
    pattern: str | None = None  # paver layout, overriding the material's default (see pavers.py)


@dataclass
class Definition:
    """A reusable, named primitive+material template placed many times via
    `instances`."""

    id: str
    primitive: Primitive
    material: str | None = None


@dataclass
class Placement:
    """Where a drawing overlay (the legend box, the scale indicator) sits,
    in scene units: its origin point, which the designer drags."""

    x: float
    y: float


@dataclass
class SceneDocument:
    """Top-level scene document: units, canvas, scale, layer order, palette
    reference, reusable definitions, and the object list."""

    units: str = "ft"
    page_width: float = 0.0
    page_height: float = 0.0
    scale: float = 1.0  # drawing units per real-world unit (e.g. pt per ft)
    layers: list[str] = field(default_factory=lambda: ["default"])
    palette: str | None = None
    definitions: dict[str, Definition] = field(default_factory=dict)
    objects: list[SceneObject] = field(default_factory=list)
    resolution_order: list[str] = field(default_factory=list)
    # Overlay positions, present only once the designer has moved them —
    # until then the defaults in `overlays.py` apply (and an untouched file
    # round-trips byte-identical).
    legend: Placement | None = None
    scale_indicator: Placement | None = None
    """Object ids in dependency order (relations + boolean ops resolved
    before anything that references them). Populated by `scene_io` during
    validation; M3 walks it to resolve geometry."""

    def get(self, object_id: str) -> SceneObject:
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        raise SchemaError(f"no object with id '{object_id}'")
