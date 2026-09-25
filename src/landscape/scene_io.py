"""Scene file I/O and validation (M2).

Loading uses `ruamel.yaml`'s round-trip loader so the raw representation
(comments, key order, quote style) survives even though this module reads it
into a `SceneDocument` for the geometry engine. The editor's lossless
round-trip requirement (M8) dumps the raw representation straight back out
via `dump_raw`, never through the dataclass model — `load_raw`/`dump_raw`
are what makes "load, don't touch, save, get the same bytes back" possible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .schema import (
    Definition,
    Placement,
    SceneDocument,
    SceneObject,
    SchemaError,
    parse_boolean,
    parse_primitive,
    parse_relation,
    parse_transform,
)

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # don't line-wrap long polygon point lists on dump
_yaml.indent(mapping=2, sequence=4, offset=2)  # matches the style used in hand-authored scenes


def load_raw(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return _yaml.load(f)


def dump_raw(data: Any, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(data, f)


def line_of(node: Any) -> int | None:
    """1-based source line for a ruamel-loaded mapping/sequence node, if
    the node carries line/column info."""
    lc = getattr(node, "lc", None)
    if lc is None:
        return None
    return lc.line + 1


def load_scene(path: str | Path) -> SceneDocument:
    return parse_scene(load_raw(path))


def parse_scene(raw: Any) -> SceneDocument:
    if raw is None:
        raise SchemaError("empty scene document")

    doc = SceneDocument(
        units=raw.get("units", "ft"),
        page_width=_require_number(raw, "page_width"),
        page_height=_require_number(raw, "page_height"),
        scale=_require_number(raw, "scale"),
        layers=list(raw.get("layers", ["default"])),
        palette=raw.get("palette"),
    )

    for def_id, def_data in (raw.get("definitions") or {}).items():
        try:
            doc.definitions[def_id] = Definition(
                id=def_id,
                primitive=parse_primitive(def_data),
                material=def_data.get("material"),
            )
        except SchemaError as exc:
            raise SchemaError(
                str(exc), path=f"definitions.{def_id}", line=line_of(def_data)
            ) from exc

    seen_ids: set[str] = set()
    for i, obj_data in enumerate(raw.get("objects") or []):
        obj_id = obj_data.get("id")
        path_hint = f"objects[{i}]" if not obj_id else f"objects.{obj_id}"
        if not obj_id:
            raise SchemaError(
                "object is missing required 'id'", path=path_hint, line=line_of(obj_data)
            )
        if obj_id in seen_ids:
            raise SchemaError(
                f"duplicate object id '{obj_id}'", path=path_hint, line=line_of(obj_data)
            )
        seen_ids.add(obj_id)

        try:
            doc.objects.append(_parse_object(obj_id, obj_data, doc))
        except SchemaError as exc:
            raise SchemaError(str(exc), path=path_hint, line=line_of(obj_data)) from exc

    doc.resolution_order = validate_and_order(doc)
    doc.legend = _parse_placement(raw, "legend")
    doc.scale_indicator = _parse_placement(raw, "scale_indicator")
    return doc


OVERLAY_KEYS = ("legend", "scale_indicator")


def _parse_placement(raw: Any, key: str) -> Placement | None:
    data = raw.get(key)
    if data is None:
        return None
    try:
        return Placement(x=float(data["x"]), y=float(data["y"]))
    except (TypeError, KeyError, ValueError) as exc:
        raise SchemaError(f"'{key}' must be a mapping with numeric x and y, e.g. {{x: 1, y: 2}}", path=key,
                          line=line_of(data) or line_of(raw)) from exc


def _parse_object(obj_id: str, obj_data: Any, doc: SceneDocument) -> SceneObject:
    definition_ref = obj_data.get("definition")
    if definition_ref:
        if definition_ref not in doc.definitions:
            raise SchemaError(f"unknown definition '{definition_ref}'")
        template = doc.definitions[definition_ref]
        primitive = template.primitive
        material = obj_data.get("material", template.material)
    else:
        primitive = parse_primitive(obj_data)
        material = obj_data.get("material")

    return SceneObject(
        id=obj_id,
        primitive=primitive,
        material=material,
        layer=obj_data.get("layer", "default"),
        z=obj_data.get("z", 0),
        annotation=obj_data.get("annotation", False),
        relation=parse_relation(obj_data),
        definition=definition_ref,
        transform=parse_transform(obj_data.get("transform")),
        boolean=parse_boolean(obj_data.get("boolean")),
    )


def _require_number(raw: Any, key: str) -> float:
    if key not in raw:
        raise SchemaError(f"missing required top-level key '{key}'", line=line_of(raw))
    return float(raw[key])


def validate_and_order(doc: SceneDocument) -> list[str]:
    """Every relation and boolean op must reference an existing object,
    and the combined dependency graph must not contain a cycle. Also
    computes the resolution order M3 needs: objects with no dependency
    resolve first, then anything that only depends on already-resolved
    objects. Public (not just called from `parse_scene`) so the editor
    can re-run it after a relation edit changes the dependency graph."""

    ids = {obj.id for obj in doc.objects}
    deps: dict[str, set[str]] = {obj.id: set() for obj in doc.objects}

    for obj in doc.objects:
        if obj.relation is not None:
            ref = obj.relation.ref
            if ref not in ids:
                raise SchemaError(
                    f"relation references unknown object '{ref}'", path=f"objects.{obj.id}"
                )
            deps[obj.id].add(ref)
        if obj.boolean is not None:
            for target in obj.boolean.targets:
                if target not in ids:
                    raise SchemaError(
                        f"boolean op references unknown object '{target}'",
                        path=f"objects.{obj.id}",
                    )
                deps[obj.id].add(target)

    return resolution_order(deps)


def resolution_order(deps: dict[str, set[str]]) -> list[str]:
    """Topologically sort a dependency graph (id -> set of ids it depends
    on). Raises a readable SchemaError naming the cycle if one exists."""

    order: list[str] = []
    resolved: set[str] = set()
    remaining = dict(deps)

    while remaining:
        ready = [obj_id for obj_id, refs in remaining.items() if refs <= resolved]
        if not ready:
            cycle = " -> ".join(list(remaining) + [next(iter(remaining))])
            raise SchemaError(f"cycle in object relations: {cycle}")
        for obj_id in sorted(ready):
            order.append(obj_id)
            resolved.add(obj_id)
            del remaining[obj_id]

    return order
