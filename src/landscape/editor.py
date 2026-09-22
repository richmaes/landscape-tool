"""Graphical editor (M8) — still an early slice, not the whole milestone.

Landed so far: load a scene, show the same flat-mode picture `render_flat`
produces, pan/zoom, select an object, drag it to move it, use the
properties panel to change its rotation/scale/material, and save (Ctrl+S
or File > Save/Save As) back to disk losslessly — `save_scene` writes
through `scene_io.dump_raw` on the same `ruamel.yaml` round-trip document
`load_raw` produced, so an object nobody touched comes back
byte-identical, per the project's hard round-trip requirement (see
TODO.md). There's still no undo/redo, no create-object, no relation
editing, and no live rule-checker feedback — see the M8 checklist in
TODO.md for the real state.

Uses PySide6 (`QGraphicsScene`/`QGraphicsView`), per the UI-stack decision
recorded in TODO.md.

Every design object becomes its own `QGraphicsItem` (tagged with its scene
id via `setData(0, ...)`) so selection and dragging hit-test individual
objects rather than a flattened image. Annotations and keepout zones are
drawn but not made selectable/movable — they're derived/technical markers,
not primary design objects, at least for this slice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QLabel,
    QMainWindow,
    QSplitter,
    QWidget,
)
from shapely.geometry.base import BaseGeometry

from .geometry import ResolvedObject, ResolvedScene
from .materials import Material, MaterialLibrary
from .schema import SceneDocument, SceneObject

_OBJECT_ID_ROLE = 0


def _path_for_geometry(geom: BaseGeometry, page_height: float) -> QPainterPath:
    """Same y-flip convention as `render_flat`: scene coordinates are
    +y-north/up, Qt scene coordinates are +y-down."""
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)  # so polygon holes render as holes

    if geom.geom_type in ("Polygon", "MultiPolygon"):
        polygons = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polygons:
            for ring in (poly.exterior, *poly.interiors):
                coords = list(ring.coords)
                if not coords:
                    continue
                path.moveTo(coords[0][0], page_height - coords[0][1])
                for x, y in coords[1:]:
                    path.lineTo(x, page_height - y)
                path.closeSubpath()
    else:
        lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for line in lines:
            coords = list(line.coords)
            if not coords:
                continue
            path.moveTo(coords[0][0], page_height - coords[0][1])
            for x, y in coords[1:]:
                path.lineTo(x, page_height - y)

    return path


def _darken(color: QColor, factor: float = 0.7) -> QColor:
    return QColor(int(color.red() * factor), int(color.green() * factor), int(color.blue() * factor))


class EditableItem(QGraphicsPathItem):
    """A design object the designer can select and drag. Dragging is baked
    straight into `scene_object.transform` (and the item's own path)
    rather than left sitting in Qt's `pos()`, so a later rebuild from the
    document reproduces the same position exactly once — no double
    counting between "where Qt thinks the item is" and "what the document
    says"."""

    def __init__(
        self,
        path: QPainterPath,
        scene_object: SceneObject,
        on_moved: Callable[[str], None] | None = None,
    ):
        super().__init__(path)
        self.scene_object = scene_object
        self._on_moved = on_moved
        self.setData(_OBJECT_ID_ROLE, scene_object.id)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            delta = value - self.pos()
            if delta.x() or delta.y():
                # Qt's y is flipped relative to the scene's +y-north convention.
                self.scene_object.transform.tx += delta.x()
                self.scene_object.transform.ty += -delta.y()
                self.setPath(self.path().translated(delta.x(), delta.y()))
                if self._on_moved:
                    self._on_moved(self.scene_object.id)
            return self.pos()  # veto Qt's own pos(); the path already moved
        return super().itemChange(change, value)


def _add_material_item(
    scene: QGraphicsScene,
    obj: ResolvedObject,
    material: Material,
    page_height: float,
    scene_object: SceneObject | None = None,
    on_moved: Callable[[str], None] | None = None,
) -> QGraphicsPathItem:
    path = _path_for_geometry(obj.geometry, page_height)
    if scene_object is not None:
        item: QGraphicsPathItem = EditableItem(path, scene_object, on_moved)
    else:
        item = QGraphicsPathItem(path)
        item.setData(_OBJECT_ID_ROLE, obj.id)

    fill = QColor(material.color)
    is_area = obj.geometry.geom_type in ("Polygon", "MultiPolygon")
    weight = material.edge.get("weight", 1.0) or 0.0
    edge = QColor(material.edge["color"]) if material.edge.get("color") else _darken(fill)

    item.setBrush(QBrush(fill) if is_area else QBrush(Qt.NoBrush))
    item.setPen(QPen(edge, weight) if weight > 0 else QPen(Qt.NoPen))
    scene.addItem(item)
    return item


def _add_annotation_item(scene: QGraphicsScene, obj: ResolvedObject, label: str, page_height: float) -> None:
    """Annotations and keepout zones: dashed outline, no fill, a text
    label at the centroid — mirrors `render_flat._draw_annotation`. Not
    selectable/movable in this slice."""
    path = _path_for_geometry(obj.geometry, page_height)
    item = QGraphicsPathItem(path)
    item.setData(_OBJECT_ID_ROLE, obj.id)
    pen = QPen(QColor(64, 64, 64))
    pen.setStyle(Qt.DashLine)
    pen.setWidthF(0.05)
    item.setPen(pen)
    item.setBrush(QBrush(Qt.NoBrush))
    scene.addItem(item)

    centroid = obj.geometry.centroid
    text = QGraphicsSimpleTextItem(label)
    font = text.font()
    font.setPointSizeF(0.8)
    text.setFont(font)
    text.setPos(centroid.x, page_height - centroid.y)
    scene.addItem(text)


def build_graphics_scene(
    scene: ResolvedScene,
    materials: MaterialLibrary,
    page_height: float,
    show_annotations: bool = False,
    doc: SceneDocument | None = None,
    on_object_moved: Callable[[str], None] | None = None,
) -> QGraphicsScene:
    """The same picture `render_flat` draws, as interactive QGraphicsItems
    instead of a flattened cairo surface. Pass `doc` (the source
    `SceneDocument`) to make material-bearing objects selectable/movable —
    without it, this builds a read-only preview, same as before this
    became editable. `on_object_moved(object_id)` fires after a drag bakes
    itself into that object's transform, for anyone (the editor's
    round-trip save) that needs to react to it."""
    gscene = QGraphicsScene()

    for obj in scene.paint_order():
        if obj.geometry.is_empty:
            continue
        if obj.annotation and not show_annotations:
            continue
        if obj.annotation or obj.rule:
            label = f"{obj.id} ({obj.rule})" if obj.rule else obj.id
            _add_annotation_item(gscene, obj, label, page_height)
            continue
        material = materials.resolve(obj.material)
        scene_object = doc.get(obj.id) if doc is not None else None
        _add_material_item(gscene, obj, material, page_height, scene_object, on_object_moved)

    return gscene


class SceneGraphicsView(QGraphicsView):
    """Zoom on the wheel; pan while space is held (matching common
    design-tool convention); plain drag otherwise selects/moves items —
    `QGraphicsView.ScrollHandDrag` as the *default* drag mode would
    swallow every left-drag for panning and starve item selection, so it's
    only active while space is down."""

    def __init__(self, scene: QGraphicsScene | None = None):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self.setDragMode(QGraphicsView.NoDrag)
        else:
            super().keyReleaseEvent(event)


class PropertiesPanel(QWidget):
    """Rotate/scale/reassign-material for whatever's selected. Not a
    swatch picker yet (M4's `render_swatch()` exists for that, just not
    wired in here) — a name-only combo box for now."""

    def __init__(self, material_ids: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.id_label = QLabel("—")
        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setRange(-3600, 3600)
        self.rotation_spin.setSuffix("°")
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 100)
        self.scale_spin.setSingleStep(0.05)
        self.material_combo = QComboBox()
        self.material_combo.addItems(material_ids)

        layout = QFormLayout(self)
        layout.addRow("Object", self.id_label)
        layout.addRow("Rotation", self.rotation_spin)
        layout.addRow("Scale", self.scale_spin)
        layout.addRow("Material", self.material_combo)
        self.setEnabled(False)

    def show_object(self, obj: SceneObject) -> None:
        self.id_label.setText(obj.id)
        for widget in (self.rotation_spin, self.scale_spin, self.material_combo):
            widget.blockSignals(True)
        self.rotation_spin.setValue(obj.transform.rotation)
        self.scale_spin.setValue(obj.transform.scale)
        index = self.material_combo.findText(obj.material or "")
        self.material_combo.setCurrentIndex(index)
        for widget in (self.rotation_spin, self.scale_spin, self.material_combo):
            widget.blockSignals(False)
        self.setEnabled(True)

    def clear(self) -> None:
        self.id_label.setText("—")
        self.setEnabled(False)


class EditorWindow(QMainWindow):
    def __init__(self, materials_path: str | Path = "assets/materials.yaml"):
        super().__init__()
        self.setWindowTitle("Landscape Editor")

        from .materials import load_materials

        self._materials = load_materials(materials_path)
        self._doc: SceneDocument | None = None
        self._raw = None  # the ruamel round-trip document; source of truth for save_scene()
        self._raw_objects: dict[str, object] = {}
        self._scene_path: Path | None = None
        self._show_annotations = False
        self._selected_id: str | None = None

        self._view = SceneGraphicsView()
        self._panel = PropertiesPanel(list(self._materials.materials))
        self._panel.rotation_spin.valueChanged.connect(self._on_rotation_changed)
        self._panel.scale_spin.valueChanged.connect(self._on_scale_changed)
        self._panel.material_combo.currentTextChanged.connect(self._on_material_changed)

        splitter = QSplitter()
        splitter.addWidget(self._view)
        splitter.addWidget(self._panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.resize(1100, 800)
        self._build_menu()

    def _build_menu(self) -> None:
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QFileDialog

        file_menu = self.menuBar().addMenu("&File")

        save_action = file_menu.addAction("&Save")
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(lambda: self.save_scene())

        save_as_action = file_menu.addAction("Save &As…")

        def _save_as() -> None:
            path, _ = QFileDialog.getSaveFileName(self, "Save Scene As", "", "Scene YAML (*.yaml)")
            if path:
                self.save_scene(path)

        save_as_action.triggered.connect(_save_as)

    def load_scene(self, scene_path: str | Path, show_annotations: bool = False) -> None:
        from .scene_io import load_raw, parse_scene

        self._scene_path = Path(scene_path)
        self._raw = load_raw(scene_path)
        self._raw_objects = {node["id"]: node for node in (self._raw.get("objects") or [])}
        self._doc = parse_scene(self._raw)
        self._show_annotations = show_annotations
        self._rebuild_scene()
        self._view.fitInView(self._view.scene().itemsBoundingRect(), Qt.KeepAspectRatio)
        self.setWindowTitle(f"Landscape Editor — {Path(scene_path).name}")

    def save_scene(self, path: str | Path | None = None) -> None:
        """Write the raw (comment- and formatting-preserving) document
        back out. Only objects actually edited in this session carry new
        `material`/`transform` values (see `_sync_raw_object`) — anything
        untouched round-trips through `load_raw`/`dump_raw` exactly as
        M2 designed it to."""
        from .scene_io import dump_raw

        dump_raw(self._raw, path or self._scene_path)

    def _sync_raw_object(self, object_id: str) -> None:
        """Write an edited object's current material/transform into its
        raw YAML node, so `save_scene` picks it up. Only touches this one
        node — every other object's raw representation, comments and all,
        is untouched."""
        obj = self._doc.get(object_id)
        raw_obj = self._raw_objects.get(object_id)
        if raw_obj is None:
            return
        if obj.material is not None:
            raw_obj["material"] = obj.material
        t = obj.transform
        if t.tx or t.ty or t.rotation or t.scale != 1.0:
            raw_obj["transform"] = {"tx": t.tx, "ty": t.ty, "rotation": t.rotation, "scale": t.scale}

    def _rebuild_scene(self) -> None:
        from .geometry import resolve_scene

        # setScene() below fires selectionChanged for the outgoing scene's
        # deselection, which would otherwise clobber self._selected_id to
        # None (via _on_selection_changed) before the reselect step runs.
        previously_selected = self._selected_id
        resolved = resolve_scene(self._doc)
        gscene = build_graphics_scene(
            resolved,
            self._materials,
            self._doc.page_height,
            self._show_annotations,
            doc=self._doc,
            on_object_moved=self._sync_raw_object,
        )
        gscene.selectionChanged.connect(self._on_selection_changed)
        # PySide6 pitfall: QGraphicsView.setScene() doesn't keep the scene
        # alive on Python's side. Without this reference, the C++ object
        # gets garbage-collected out from under the view once this method
        # returns, and every signal on it after that silently misbehaves.
        self._scene = gscene
        old_transform = self._view.transform()
        self._view.setScene(gscene)
        self._view.setTransform(old_transform)
        if previously_selected:
            self._select_item_by_id(previously_selected)

    def _select_item_by_id(self, object_id: str) -> None:
        for item in self._view.scene().items():
            if item.data(_OBJECT_ID_ROLE) == object_id:
                item.setSelected(True)
                return

    def _on_selection_changed(self) -> None:
        items = self._view.scene().selectedItems()
        if len(items) == 1 and isinstance(items[0], EditableItem):
            self._selected_id = items[0].scene_object.id
            self._panel.show_object(items[0].scene_object)
        else:
            self._selected_id = None
            self._panel.clear()

    def _on_rotation_changed(self, value: float) -> None:
        if self._selected_id:
            self._doc.get(self._selected_id).transform.rotation = value
            self._sync_raw_object(self._selected_id)
            self._rebuild_scene()

    def _on_scale_changed(self, value: float) -> None:
        if self._selected_id:
            self._doc.get(self._selected_id).transform.scale = value
            self._sync_raw_object(self._selected_id)
            self._rebuild_scene()

    def _on_material_changed(self, material_id: str) -> None:
        if self._selected_id and material_id:
            self._doc.get(self._selected_id).material = material_id
            self._sync_raw_object(self._selected_id)
            self._rebuild_scene()
