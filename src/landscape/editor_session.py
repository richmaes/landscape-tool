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

from pathlib import Path
from typing import Any

from .geometry import ResolvedScene, resolve_scene
from .materials import MaterialLibrary, load_materials
from .rules import Violation, load_rules, run_rules
from .scene_io import dump_raw, load_raw, parse_scene
from .schema import SceneDocument


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

    def load(self, scene_path: str | Path) -> None:
        self.scene_path = Path(scene_path)
        self.raw = load_raw(scene_path)
        self.raw_objects = {node["id"]: node for node in (self.raw.get("objects") or [])}
        self.doc = parse_scene(self.raw)
        self.recompute()

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
            raw_obj["material"] = obj.material
        t = obj.transform
        if t.tx or t.ty or t.rotation or t.scale != 1.0:
            raw_obj["transform"] = {"tx": t.tx, "ty": t.ty, "rotation": t.rotation, "scale": t.scale}

    def set_rotation(self, object_id: str, value: float) -> None:
        self.doc.get(object_id).transform.rotation = value
        self.sync_object(object_id)
        self.recompute()

    def set_scale(self, object_id: str, value: float) -> None:
        self.doc.get(object_id).transform.scale = value
        self.sync_object(object_id)
        self.recompute()

    def set_material(self, object_id: str, material_id: str) -> None:
        self.doc.get(object_id).material = material_id
        self.sync_object(object_id)
        self.recompute()

    def save(self, path: str | Path | None = None) -> None:
        dump_raw(self.raw, path or self.scene_path)
