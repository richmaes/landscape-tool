"""Rule checker / DRC (M3b).

Constraints warn; they never block — see the "Constraints" decision in
TODO.md. The designer must be free to drag anything anywhere and be told
afterwards what is wrong, so every violation here is informational, not an
error to raise.

Rules are data: this module implements a small, fixed set of generic check
*types* (the functions in `_CHECKS`), each parameterized by data. A new
*instance* of an existing type — a new keep-out pair, a new clearance zone —
is a few lines in a rules file (see `rules/default.yaml`), no code change.
Only a genuinely new kind of check needs a new Python function, the same
trade-off M2 made for the relation vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ruamel.yaml import YAML
from shapely.geometry import box

from .geometry import ResolvedScene

_yaml = YAML(typ="safe")


@dataclass
class Violation:
    """A located, human-readable constraint violation. `location` is a
    representative (x, y) point — the offending overlap's centroid where
    there is one, otherwise the primary object's — so the editor (M8) can
    anchor the warning next to the object rather than in a log."""

    rule_id: str
    object_ids: list[str]
    message: str
    location: tuple[float, float]
    severity: str = "warning"  # constraints warn, never block


def load_rules(path: str | Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = _yaml.load(f) or {}
    return data.get("rules", [])


def run_rules(scene: ResolvedScene, rules: list[dict[str, Any]]) -> list[Violation]:
    violations: list[Violation] = []
    for spec in rules:
        rule_id = spec.get("id", "<unnamed rule>")
        check_type = spec.get("type")
        checker = _CHECKS.get(check_type)
        if checker is None:
            raise ValueError(f"unknown rule type '{check_type}' (rule id '{rule_id}')")
        violations.extend(checker(scene, spec))
    return violations


def _location(*geoms) -> tuple[float, float]:
    inter = geoms[0]
    for g in geoms[1:]:
        inter = inter.intersection(g)
    target = inter if not inter.is_empty else geoms[0]
    c = target.centroid
    return (c.x, c.y)


# ---------------------------------------------------------------------------
# Check types
# ---------------------------------------------------------------------------


def _check_keepout_material_exclusion(scene: ResolvedScene, spec: dict[str, Any]) -> list[Violation]:
    """Any object built from a `keepout` primitive is a zone; flag every
    other object whose material is in `excluded_materials` that overlaps
    it. `zone_rule`, if given, restricts this to zones whose declared
    `rule` string matches (so different keep-out purposes can carry
    different exclusion lists)."""

    excluded = set(spec.get("excluded_materials", []))
    zone_rule = spec.get("zone_rule")
    min_area = spec.get("min_area", 1e-6)
    violations = []

    for zone in scene.objects:
        if not zone.rule or (zone_rule and zone.rule != zone_rule):
            continue
        for obj in scene.objects:
            if obj.id == zone.id or obj.material not in excluded:
                continue
            overlap = zone.geometry.intersection(obj.geometry)
            if not overlap.is_empty and overlap.area > min_area:
                violations.append(
                    Violation(
                        rule_id=spec["id"],
                        object_ids=[zone.id, obj.id],
                        message=spec.get(
                            "message_template",
                            "'{obj}' ({material}) is inside keep-out zone '{zone}' ({area:.3f} sq ft overlap)",
                        ).format(obj=obj.id, material=obj.material, zone=zone.id, area=overlap.area),
                        location=_location(zone.geometry, obj.geometry),
                    )
                )
    return violations


def _check_concentricity(scene: ResolvedScene, spec: dict[str, Any]) -> list[Violation]:
    """For each declared {zone, center} pair, flag it if their centroids
    drift apart by more than `tolerance`. Checks the geometric invariant
    directly rather than trusting that a `center_of` relation was used, so
    it still catches drift in a scene authored (or hand-edited) without
    one."""

    tolerance = spec.get("tolerance", 0.01)
    violations = []
    for pair in spec["pairs"]:
        zone = scene.get(pair["zone"])
        center = scene.get(pair["center"])
        distance = zone.geometry.centroid.distance(center.geometry.centroid)
        if distance > tolerance:
            violations.append(
                Violation(
                    rule_id=spec["id"],
                    object_ids=[zone.id, center.id],
                    message=spec.get(
                        "message_template",
                        "'{zone}' is {distance:.3f} ft off-center from '{center}'",
                    ).format(zone=zone.id, center=center.id, distance=distance),
                    location=_location(zone.geometry),
                )
            )
    return violations


def _check_containment(scene: ResolvedScene, spec: dict[str, Any]) -> list[Violation]:
    """For each declared {zone, parent} pair, flag it if any part of the
    zone falls outside the parent region by more than `tolerance` ft."""

    tolerance = spec.get("tolerance", 0.0)
    min_area = spec.get("min_area", 1e-6)
    violations = []
    for pair in spec["pairs"]:
        zone = scene.get(pair["zone"])
        parent = scene.get(pair["parent"])
        outside = zone.geometry.difference(parent.geometry.buffer(tolerance))
        if not outside.is_empty and outside.area > min_area:
            violations.append(
                Violation(
                    rule_id=spec["id"],
                    object_ids=[zone.id, parent.id],
                    message=spec.get(
                        "message_template",
                        "'{zone}' extends {area:.3f} sq ft outside '{parent}'",
                    ).format(zone=zone.id, parent=parent.id, area=outside.area),
                    location=_location(outside),
                )
            )
    return violations


def _check_no_overlap_unless_stacked(scene: ResolvedScene, spec: dict[str, Any]) -> list[Violation]:
    """Every pair of non-annotation objects must not overlap unless the
    pair is explicitly listed in `exceptions` (order doesn't matter), or
    one is a boolean-op target of the other (an intentional carve-out, not
    an accidental overlap). Objects whose material is in `ignore_materials`
    are dropped entirely: ground-cover layers (lawn, mulch, sand) are base
    layers everything else legitimately sits on top of, not overlaps."""

    min_area = spec.get("min_area", 1e-6)
    exceptions = {frozenset(pair) for pair in spec.get("exceptions", [])}
    boolean_targets = {frozenset(pair) for pair in spec.get("boolean_pairs", [])}
    ignore_materials = set(spec.get("ignore_materials", []))
    candidates = [
        o for o in scene.objects if not o.annotation and o.material not in ignore_materials
    ]

    violations = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            key = frozenset((a.id, b.id))
            if key in exceptions or key in boolean_targets:
                continue
            overlap = a.geometry.intersection(b.geometry)
            if not overlap.is_empty and overlap.area > min_area:
                violations.append(
                    Violation(
                        rule_id=spec["id"],
                        object_ids=[a.id, b.id],
                        message=spec.get(
                            "message_template",
                            "'{a}' and '{b}' overlap by {area:.3f} sq ft without being marked as stacked",
                        ).format(a=a.id, b=b.id, area=overlap.area),
                        location=_location(overlap),
                    )
                )
    return violations


_DIRECTIONS: dict[str, Callable[[float, float, float, float, float], tuple]] = {
    "south": lambda minx, miny, maxx, maxy, d: (minx, miny - d, maxx, miny),
    "north": lambda minx, miny, maxx, maxy, d: (minx, maxy, maxx, maxy + d),
    "east": lambda minx, miny, maxx, maxy, d: (maxx, miny, maxx + d, maxy),
    "west": lambda minx, miny, maxx, maxy, d: (minx - d, miny, minx, maxy),
}


def _check_directional_clearance(scene: ResolvedScene, spec: dict[str, Any]) -> list[Violation]:
    """Flag anything obstructing a clearance zone extending `distance` ft
    from one edge of `object` in `direction` ('north'/'south'/'east'/'west').
    Meant for access clearance in front of equipment (e.g. a mechanical
    bay) — not wired to a real object yet since the mechanical bay side is
    still an open question (see TODO.md); exercised against the example
    scene's `shed` as a stand-in. Ground-cover materials in
    `ignore_materials` (lawn, mulch, etc.) never count as obstructions —
    walking across them is fine; only real objects (decking, walls,
    equipment) do."""

    obj = scene.get(spec["object"])
    direction = spec["direction"]
    if direction not in _DIRECTIONS:
        raise ValueError(f"unknown clearance direction '{direction}'")
    distance = spec["distance"]
    min_area = spec.get("min_area", 1e-6)
    ignore = set(spec.get("ignore", [])) | {obj.id}
    ignore_materials = set(spec.get("ignore_materials", []))

    zone = box(*_DIRECTIONS[direction](*obj.geometry.bounds, distance))

    violations = []
    for other in scene.objects:
        if other.id in ignore or other.annotation or other.material in ignore_materials:
            continue
        overlap = zone.intersection(other.geometry)
        if not overlap.is_empty and overlap.area > min_area:
            violations.append(
                Violation(
                    rule_id=spec["id"],
                    object_ids=[obj.id, other.id],
                    message=spec.get(
                        "message_template",
                        "'{other}' obstructs the {direction} access clearance in front of '{obj}'",
                    ).format(other=other.id, direction=direction, obj=obj.id),
                    location=_location(overlap),
                )
            )
    return violations


_CHECKS: dict[str, Callable[[ResolvedScene, dict[str, Any]], list[Violation]]] = {
    "keepout_material_exclusion": _check_keepout_material_exclusion,
    "concentricity": _check_concentricity,
    "containment": _check_containment,
    "no_overlap_unless_stacked": _check_no_overlap_unless_stacked,
    "directional_clearance": _check_directional_clearance,
}
