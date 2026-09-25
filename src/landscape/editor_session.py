"""Non-GUI editor state and logic (M8): load a scene, mutate it, sync
edits into the raw round-trip document, run the rule checker, save.

Deliberately has no PySide6 import anywhere in this file. `EditorWindow`
(in `editor.py`) wraps a `EditorSession` and translates it into widgets
and draw calls, but everything here is plain Python — usable from a
future headless/batch tool (M8b) without pulling in Qt at all, and
testable without `qtbot`. The GUI/core split this project already had
(schema/scene_io/geometry/materials/render_flat/rules never imported Qt)
now extends to the editor's own orchestration, not just its calculations.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .geometry import ResolvedScene, resolve_scene
from .materials import MaterialLibrary, load_materials
from .rules import Violation, load_rules, run_rules
from .scene_io import dump_raw, load_raw, parse_scene, validate_and_order
from .schema import SceneDocument, SceneObject, SchemaError, parse_primitive, parse_relation, primitive_to_raw_dict

# The closed relation vocabulary (M2) and the raw YAML keys each one
# owns, so switching an object from one relation type to another cleans
# up the previous type's keys rather than leaving stale ones behind.
RELATION_TYPES: list[str] = ["center_of", "mirror_of", "relative_to", "chord_of"]
_RELATION_RAW_KEYS: dict[str, list[str]] = {
    "center_of": ["center_of"],
    "mirror_of": ["mirror_of", "about_x", "about_y"],
    "relative_to": ["relative_to", "dx", "dy"],
    "chord_of": ["chord_of", "offset", "angle_deg"],
}

_MAX_UNDO_DEPTH = 100

# Default field values for each creatable primitive kind, as a function
# of the page center (cx, cy) — deliberately excludes `keepout`: it needs
# a `rule` string and a nested `shape`, neither of which the create-object
# palette has a control for yet.
_DEFAULT_PRIMITIVE_KWARGS: dict[str, Any] = {
    "circle": lambda cx, cy: {"cx": cx, "cy": cy, "r": 1.0},
    "ellipse": lambda cx, cy: {"cx": cx, "cy": cy, "rx": 1.0, "ry": 1.0},
    "rect": lambda cx, cy: {"x": cx - 1.0, "y": cy - 1.0, "width": 2.0, "height": 2.0},
    "polygon": lambda cx, cy: {"points": [(cx - 1, cy - 1), (cx + 1, cy - 1), (cx, cy + 1)]},
    "regular_polygon": lambda cx, cy: {"cx": cx, "cy": cy, "sides": 6, "size": 1.0},
    "line": lambda cx, cy: {"x1": cx - 1, "y1": cy, "x2": cx + 1, "y2": cy},
    "fence_line": lambda cx, cy: {"points": [(cx - 1, cy), (cx + 1, cy)]},
    "wavy_path": lambda cx, cy: {"points": [(cx - 1, cy), (cx + 1, cy)]},
    "walkway": lambda cx, cy: {"points": [(cx - 1, cy), (cx + 1, cy)], "width": 1.0},
}

CREATABLE_PRIMITIVE_KINDS: list[str] = list(_DEFAULT_PRIMITIVE_KWARGS)



def _pop_trailing_comment(node: CommentedMap) -> list | None:
    """Detach the comment that follows a mapping's last value — where
    ruamel keeps the blank line separating one object from the next. For
    a block-style nested mapping it sits on *that* mapping's last key, so
    recurse into it."""
    if not node:
        return None
    last_key = list(node.keys())[-1]
    entry = node.ca.items.get(last_key)
    if entry and len(entry) > 2 and entry[2] is not None:
        comment, entry[2] = entry[2], None
        return comment
    value = node[last_key]
    if isinstance(value, CommentedMap) and not value.fa.flow_style():
        return _pop_trailing_comment(value)
    return None


def _attach_trailing_comment(node: CommentedMap, comment: list | None) -> None:
    if comment is None or not node:
        return
    last_key = list(node.keys())[-1]
    value = node[last_key]
    if isinstance(value, CommentedMap) and value and not value.fa.flow_style():
        _attach_trailing_comment(value, comment)
        return
    node.ca.items.setdefault(last_key, [None, None, None, None])[2] = comment


def _write_changed_fields(node: Any, data: dict[str, Any]) -> None:
    """Copy a primitive's fields into its raw YAML node, touching only the
    ones whose value actually changed (so formatting and comments on the
    rest survive). Point lists are written as compact flow lists, like
    hand-written ones; a keepout's nested `shape` is updated in place."""
    for key, value in data.items():
        if key == "type":
            continue
        current = node.get(key)
        if isinstance(value, dict):
            if isinstance(current, dict):
                _write_changed_fields(current, value)
            continue
        if key not in node or current == value:
            continue  # absent fields keep their defaults; unchanged ones stay as written
        if isinstance(value, list):
            seq = CommentedSeq([_flow_seq(p) if isinstance(p, list) else p for p in value])
            seq.fa.set_flow_style()
            value = seq
        node[key] = value


def _flow_seq(items: list) -> CommentedSeq:
    seq = CommentedSeq(items)
    seq.fa.set_flow_style()
    return seq


def _set_keeping_trailing_gap(node: CommentedMap, key: str, value: Any) -> None:
    """`node[key] = value`, but the blank line after the object stays after
    the object. A plain assignment gets this wrong two ways: a *new* key
    is appended after the last key's trailing comment (so the gap lands
    above it), and *replacing* a nested mapping that was last throws away
    the comment it carried."""
    comment = _pop_trailing_comment(node)
    node[key] = value
    _attach_trailing_comment(node, comment)

class EditorSession:
    def __init__(self, materials_path: str | Path = "assets/materials.yaml", rules_path: str | Path | None = None):
        self.materials: MaterialLibrary = load_materials(materials_path)
        self.rules: list[dict[str, Any]] = load_rules(rules_path) if rules_path else []
        self.doc: SceneDocument | None = None
        self.raw: Any = None  # the ruamel round-trip document; source of truth for save()
        self.raw_objects: dict[str, Any] = {}
        self.scene_path: Path | None = None
        self.resolved: ResolvedScene | None = None
        self.violations: list[Violation] = []
        # Each entry is (doc, raw, state_id) — see `dirty`.
        self._undo_stack: list[tuple[SceneDocument, Any, int]] = []
        self._redo_stack: list[tuple[SceneDocument, Any, int]] = []
        self._state_id = 0
        self._saved_state_id = 0
        self._next_state_id = 1
        # Called (no arguments) whenever `dirty` may have changed — load,
        # any edit's push_undo(), undo, redo, save. Plain callable, so this
        # module stays free of Qt; the editor window hangs its unsaved
        # indicator off it.
        self.on_state_change: Callable[[], None] | None = None

    @property
    def dirty(self) -> bool:
        """True when the document differs from what was last loaded or
        saved. Every edit gets a fresh, never-reused state id, and undo/
        redo carry those ids with their snapshots — so undoing back to
        the saved state reads as clean again, while a *new* edit made
        after undoing never gets mistaken for the saved state."""
        return self._state_id != self._saved_state_id

    @property
    def revision(self) -> int:
        """An id for the document's current content: changes with every
        edit, and returns to an earlier value when undo/redo returns to that
        earlier content — so it can key a cache of anything derived from
        the document (the editor's art preview)."""
        return self._state_id

    def _notify_state_change(self) -> None:
        if self.on_state_change:
            self.on_state_change()

    def load(self, scene_path: str | Path) -> None:
        self.scene_path = Path(scene_path)
        self.raw = load_raw(scene_path)
        self.raw_objects = {node["id"]: node for node in (self.raw.get("objects") or [])}
        self.doc = parse_scene(self.raw)
        self._undo_stack = []
        self._redo_stack = []
        self._state_id = self._saved_state_id = 0
        self._next_state_id = 1
        self.recompute()
        self._notify_state_change()

    def push_undo(self) -> None:
        """Snapshot the current doc+raw before a mutation, so `undo()` can
        get back to it. Any new snapshot invalidates the redo stack —
        standard undo/redo semantics: you can't redo past a fresh edit.
        `doc` (plain dataclasses) and `raw` (a ruamel round-trip tree)
        both deepcopy safely and independently — verified directly rather
        than assumed, since ruamel's CommentedMap isn't a plain dict."""
        self._undo_stack.append((copy.deepcopy(self.doc), copy.deepcopy(self.raw), self._state_id))
        if len(self._undo_stack) > _MAX_UNDO_DEPTH:
            self._undo_stack.pop(0)
        self._redo_stack = []
        self._state_id = self._next_state_id
        self._next_state_id += 1
        self._notify_state_change()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append((self.doc, self.raw, self._state_id))
        self.doc, self.raw, self._state_id = self._undo_stack.pop()
        self.raw_objects = {node["id"]: node for node in (self.raw.get("objects") or [])}
        self.recompute()
        self._notify_state_change()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append((self.doc, self.raw, self._state_id))
        self.doc, self.raw, self._state_id = self._redo_stack.pop()
        self.raw_objects = {node["id"]: node for node in (self.raw.get("objects") or [])}
        self.recompute()
        self._notify_state_change()

    def recompute(self) -> None:
        """Re-resolve geometry and re-run the rule checker. Called after
        any edit that should be reflected in both the picture and the
        violation list."""
        self.resolved = resolve_scene(self.doc)
        self.violations = run_rules(self.resolved, self.rules) if self.rules else []

    def sync_object(self, object_id: str) -> None:
        """Write an edited object's current material/transform into its
        raw YAML node, so `save` picks it up. Only touches this one node
        — every other object's raw representation, comments and all, is
        untouched."""
        raw_obj = self.raw_objects.get(object_id)
        if raw_obj is None:
            return
        obj = self.doc.get(object_id)
        if obj.material is not None:
            _set_keeping_trailing_gap(raw_obj, "material", obj.material)
        t = obj.transform
        if t.tx or t.ty or t.rotation or t.scale != 1.0:
            _set_keeping_trailing_gap(
                raw_obj, "transform", CommentedMap(tx=t.tx, ty=t.ty, rotation=t.rotation, scale=t.scale)
            )

    def set_overlay_position(self, name: str, x: float, y: float) -> None:
        """Move the legend box or scale indicator (`name` is `legend` or
        `scale_indicator`) to a new origin point, in scene units. Undoable,
        and written to the scene file as `name: {x, y}` — only from the
        first move on, so an untouched file keeps round-tripping unchanged."""
        from .scene_io import OVERLAY_KEYS
        from .schema import Placement

        if name not in OVERLAY_KEYS:
            raise ValueError(f"unknown overlay '{name}' (use one of: {', '.join(OVERLAY_KEYS)})")
        self.push_undo()
        setattr(self.doc, name, Placement(x=round(x, 3), y=round(y, 3)))
        self.raw[name] = CommentedMap(x=round(x, 3), y=round(y, 3))
        self.recompute()
        self.autosave()

    def set_dimensions(self, object_id: str, width: float | None = None, height: float | None = None) -> None:
        """Reshape an object to `width` and/or `height` (scene units, after
        its scale — what the properties panel shows), independently rather
        than by uniform scale, keeping its centre in place (see
        `dimensions.py`). Undoable; only the primitive fields that actually
        change are rewritten in the YAML. Raises ValueError if the object
        can't be resized this way."""
        from .dimensions import resized_primitive

        obj = self.doc.get(object_id)
        new = resized_primitive(obj, width, height)
        self.push_undo()
        obj.primitive = new
        raw_obj = self.raw_objects.get(object_id)
        if raw_obj is not None:
            _write_changed_fields(raw_obj, primitive_to_raw_dict(new))
        self.recompute()
        self.autosave()

    def set_solid(self, object_id: str, base: float | None = None, height: float | None = None) -> None:
        """Set an object's own 3D base and/or height (feet), for the 3D view.
        A value left as None keeps what the object has now (its own solid,
        or what it inherits). Undoable; saved as a compact `solid: {base,
        height}`."""
        from .dimensions import _num
        from .schema import Solid
        from .solids import effective_solid

        for value in (base, height):
            if value is not None and value < 0:
                raise ValueError("base and height can't be negative")
        current = effective_solid(self.resolved.get(object_id), self.materials)
        solid = Solid(
            base=float(base if base is not None else current.base),
            height=float(height if height is not None else current.height),
        )
        self.push_undo()
        self.doc.get(object_id).solid = solid
        raw_obj = self.raw_objects.get(object_id)
        if raw_obj is not None:
            node = CommentedMap(base=_num(solid.base), height=_num(solid.height))
            node.fa.set_flow_style()
            _set_keeping_trailing_gap(raw_obj, "solid", node)
        self.recompute()
        self.autosave()

    def set_pattern(self, object_id: str, pattern: str) -> None:
        """Choose a paver layout for one object (see `pavers.PATTERNS`),
        overriding its material's default. Undoable; saved as `pattern:`."""
        from .pavers import PATTERNS

        if pattern not in PATTERNS:
            raise ValueError(f"unknown paver pattern '{pattern}'")
        self.push_undo()
        self.doc.get(object_id).pattern = pattern
        raw_obj = self.raw_objects.get(object_id)
        if raw_obj is not None:
            _set_keeping_trailing_gap(raw_obj, "pattern", pattern)
        self.recompute()
        self.autosave()

    def set_rotation(self, object_id: str, value: float) -> None:
        self.push_undo()
        self.doc.get(object_id).transform.rotation = value
        self.sync_object(object_id)
        self.recompute()
        self.autosave()

    def set_scale(self, object_id: str, value: float) -> None:
        self.push_undo()
        self.doc.get(object_id).transform.scale = value
        self.sync_object(object_id)
        self.recompute()
        self.autosave()

    def set_material(self, object_id: str, material_id: str) -> None:
        self.push_undo()
        self.doc.get(object_id).material = material_id
        self.sync_object(object_id)
        self.recompute()
        self.autosave()

    def set_relation(self, object_id: str, relation_type: str | None, ref: str | None = None, **params: Any) -> None:
        """Set (`relation_type` + `ref` [+ params]) or clear
        (`relation_type=None`) an object's relation — "a 'keep centred on
        firepit' checkbox, a mirror link," per M8's checklist. A relation
        isn't just a per-object property like material/transform: it
        changes the dependency graph, so this re-runs `validate_and_order`
        (unknown ref, or a cycle) rather than trusting the edit is safe.
        On failure, automatically rolls back to the pre-edit snapshot —
        an invalid relation must never leave the session broken even if
        the caller forgets to call `undo()` after catching the error."""
        self.push_undo()

        obj = self.doc.get(object_id)
        raw_obj = self.raw_objects.get(object_id)

        obj.relation = None
        if raw_obj is not None:
            for keys in _RELATION_RAW_KEYS.values():
                for key in keys:
                    raw_obj.pop(key, None)

        if relation_type is not None:
            if relation_type not in RELATION_TYPES:
                raise ValueError(f"unknown relation type '{relation_type}' (expected one of {RELATION_TYPES})")
            if not ref:
                raise ValueError(f"{relation_type} requires a target object id")
            obj.relation = parse_relation({relation_type: ref, **params})
            if raw_obj is not None:
                raw_obj[relation_type] = ref
                raw_obj.update(params)

        try:
            self.doc.resolution_order = validate_and_order(self.doc)
        except SchemaError:
            self.doc, self.raw, self._state_id = self._undo_stack.pop()
            self.raw_objects = {node["id"]: node for node in (self.raw.get("objects") or [])}
            self.recompute()
            self._notify_state_change()  # a rejected edit leaves nothing unsaved
            raise

        self.recompute()
        self.autosave()

    def create_object(self, kind: str, object_id: str | None = None) -> str:
        """Add a new object of the given M2 primitive `kind`, centered on
        the page, with sensible default dimensions. Undoable like any
        other edit. Returns the new object's id (generated as
        `<kind>_<n>` unless `object_id` is given) so the caller can
        select it immediately."""
        if kind not in _DEFAULT_PRIMITIVE_KWARGS:
            raise ValueError(
                f"cannot create a '{kind}' from the palette (supported: {CREATABLE_PRIMITIVE_KINDS})"
            )

        self.push_undo()

        object_id = object_id or self._generate_id(kind)
        cx, cy = self.doc.page_width / 2, self.doc.page_height / 2
        kwargs = _DEFAULT_PRIMITIVE_KWARGS[kind](cx, cy)
        primitive = parse_primitive({"type": kind, **kwargs})
        z = max((o.z for o in self.doc.objects), default=0) + 1
        layer = self.doc.layers[0] if self.doc.layers else "default"

        self.doc.objects.append(SceneObject(id=object_id, primitive=primitive, layer=layer, z=z))
        self.doc.resolution_order.append(object_id)  # no relation/boolean deps: safe to resolve last

        raw_node: dict[str, Any] = {"id": object_id, **primitive_to_raw_dict(primitive), "layer": layer, "z": z}
        self.raw.setdefault("objects", []).append(raw_node)
        self.raw_objects[object_id] = raw_node

        self.recompute()
        self.autosave()
        return object_id

    def _generate_id(self, kind: str) -> str:
        existing = {o.id for o in self.doc.objects}
        n = 1
        while f"{kind}_{n}" in existing:
            n += 1
        return f"{kind}_{n}"

    def save(self, path: str | Path | None = None) -> None:
        """Write the document to `path`, or back to the file it came from.
        Saving to a new path ("Save As") makes that the file being edited
        from here on, so the next plain save — and what "saved" means —
        refer to it."""
        dump_raw(self.raw, path or self.scene_path)
        self._discard_autosave()  # the old path's sidecar, if the path is changing
        if path is not None:
            self.scene_path = Path(path)
        self._saved_state_id = self._state_id
        self._notify_state_change()

    @property
    def autosave_path(self) -> Path | None:
        return self.scene_path.with_suffix(self.scene_path.suffix + ".autosave") if self.scene_path else None

    def autosave(self) -> None:
        """Write the in-progress edit to a sidecar file after every
        mutation, so a crash never silently discards hand edits — the
        M8 requirement this satisfies doesn't need a restore-on-load
        prompt to be true; it needs edits to never live only in memory."""
        if self.autosave_path is not None:
            dump_raw(self.raw, self.autosave_path)

    def _discard_autosave(self) -> None:
        """An explicit save() supersedes the autosave — remove it so a
        stale sidecar file doesn't linger once the real file is current."""
        path = self.autosave_path
        if path is not None and path.exists():
            path.unlink()

    def export(self, path: str | Path, mode: str = "flat", **kwargs: Any) -> None:
        """Render the current (edited) scene to an image file through the
        same dispatcher `landscape render` and export recipes use
        (`render.render_to_file`), so the editor's export and the CLI's
        produce identical output for the same scene and options. `mode` is
        `flat` (M5) or `art` (M6); raises ValueError for an unsupported
        mode or file type."""
        from .render import render_to_file

        render_to_file(self.doc, self.resolved, self.materials, Path(path), mode=mode, **kwargs)
