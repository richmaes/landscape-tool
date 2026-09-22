"""Graphical editor (M8) — still an early slice, not the whole milestone.

Landed so far: load a scene, show the same flat-mode picture `render_flat`
produces, pan/zoom, select an object, drag it to move it, use the
properties panel to change its rotation/scale/material, save (Ctrl+S or
File > Save/Save As) back to disk losslessly, and — if a rules file is
given — live rule-checker feedback: a marker at each violation's location
plus a dashed highlight on every object it names, both carrying the
violation's message as a tooltip, recomputed on every edit (this also
closes M3b's last open item), Ctrl+Z/Ctrl+Shift+Z undo/redo (one snapshot
per drag *gesture*, not per pixel — see `EditableItem`), autosave to a
`.autosave` sidecar after every edit, layer visibility toggling, and
File > Export… straight to PNG/SVG/PDF. There's still no create-object
and no relation editing — see the M8 checklist in TODO.md for the real
state.

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
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QWidget,
)
from shapely.geometry.base import BaseGeometry

from .editor_session import CREATABLE_PRIMITIVE_KINDS, RELATION_TYPES, EditorSession
from .geometry import ResolvedObject, ResolvedScene
from .materials import Material, MaterialLibrary
from .rules import Violation
from .schema import SceneDocument, SceneObject, SchemaError

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
        on_drag_start: Callable[[], None] | None = None,
        on_drag_end: Callable[[], None] | None = None,
    ):
        super().__init__(path)
        self.scene_object = scene_object
        self._on_moved = on_moved
        self._on_drag_start = on_drag_start
        self._on_drag_end = on_drag_end
        self._dragging = False
        self.setData(_OBJECT_ID_ROLE, scene_object.id)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            delta = value - self.pos()
            if delta.x() or delta.y():
                if not self._dragging:
                    # One undo snapshot per drag *gesture*, not per pixel:
                    # take it before the first change this press applies.
                    self._dragging = True
                    if self._on_drag_start:
                        self._on_drag_start()
                # Qt's y is flipped relative to the scene's +y-north convention.
                self.scene_object.transform.tx += delta.x()
                self.scene_object.transform.ty += -delta.y()
                self.setPath(self.path().translated(delta.x(), delta.y()))
                if self._on_moved:
                    self._on_moved(self.scene_object.id)
            return self.pos()  # veto Qt's own pos(); the path already moved
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._dragging:
            self._dragging = False
            if self._on_drag_end:
                self._on_drag_end()


def _add_material_item(
    scene: QGraphicsScene,
    obj: ResolvedObject,
    material: Material,
    page_height: float,
    scene_object: SceneObject | None = None,
    on_moved: Callable[[str], None] | None = None,
    on_drag_start: Callable[[], None] | None = None,
    on_drag_end: Callable[[], None] | None = None,
) -> QGraphicsPathItem:
    path = _path_for_geometry(obj.geometry, page_height)
    if scene_object is not None:
        item: QGraphicsPathItem = EditableItem(path, scene_object, on_moved, on_drag_start, on_drag_end)
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
    hidden_layers: set[str] | None = None,
    on_drag_start: Callable[[], None] | None = None,
    on_drag_end: Callable[[], None] | None = None,
) -> QGraphicsScene:
    """The same picture `render_flat` draws, as interactive QGraphicsItems
    instead of a flattened cairo surface. Pass `doc` (the source
    `SceneDocument`) to make material-bearing objects selectable/movable —
    without it, this builds a read-only preview, same as before this
    became editable. `on_object_moved(object_id)` fires after a drag bakes
    itself into that object's transform, for anyone (the editor's
    round-trip save) that needs to react to it; `on_drag_start`/
    `on_drag_end` bracket one whole drag *gesture* (for one undo snapshot
    per drag, not per pixel — see `EditableItem`). `hidden_layers` skips
    objects on those layers entirely — "toggle layers" from M8's
    checklist; toggling render *modes* is a separate, still-open item
    since there's only flat mode to toggle to until M6 exists."""
    gscene = QGraphicsScene()
    hidden_layers = hidden_layers or set()

    for obj in scene.paint_order():
        if obj.geometry.is_empty:
            continue
        if obj.layer in hidden_layers:
            continue
        if obj.annotation and not show_annotations:
            continue
        if obj.annotation or obj.rule:
            label = f"{obj.id} ({obj.rule})" if obj.rule else obj.id
            _add_annotation_item(gscene, obj, label, page_height)
            continue
        material = materials.resolve(obj.material)
        scene_object = doc.get(obj.id) if doc is not None else None
        _add_material_item(
            gscene, obj, material, page_height, scene_object, on_object_moved, on_drag_start, on_drag_end
        )

    return gscene


_VIOLATION_COLOR = QColor(214, 39, 39)


def add_violation_overlays(gscene: QGraphicsScene, violations: list[Violation], page_height: float) -> None:
    """Closes M3b's last open item: a dashed highlight on every object a
    violation names, plus a marker at its location, both carrying the
    violation's message as a tooltip — feedback attached to the
    offending object, not logged somewhere separate from it."""

    items_by_id = {
        item.data(_OBJECT_ID_ROLE): item for item in gscene.items() if item.data(_OBJECT_ID_ROLE)
    }

    for violation in violations:
        tooltip = f"[{violation.rule_id}] {violation.message}"
        for object_id in violation.object_ids:
            item = items_by_id.get(object_id)
            if item is None or not isinstance(item, QGraphicsPathItem):
                continue
            highlight = QGraphicsPathItem(item.path())
            pen = QPen(_VIOLATION_COLOR)
            pen.setWidthF(0.08)
            pen.setStyle(Qt.DashLine)
            highlight.setPen(pen)
            highlight.setBrush(QBrush(Qt.NoBrush))
            highlight.setZValue(999)
            highlight.setToolTip(tooltip)
            gscene.addItem(highlight)

        _add_violation_marker(gscene, violation, page_height, tooltip)


def _add_violation_marker(
    gscene: QGraphicsScene, violation: Violation, page_height: float, tooltip: str
) -> None:
    x, y = violation.location
    qx, qy = x, page_height - y
    radius = 0.5

    marker = QGraphicsEllipseItem(qx - radius, qy - radius, radius * 2, radius * 2)
    marker.setBrush(QBrush(_VIOLATION_COLOR))
    marker.setPen(QPen(QColor(120, 0, 0), 0.04))
    marker.setZValue(1000)
    marker.setToolTip(tooltip)
    gscene.addItem(marker)

    bang = QGraphicsSimpleTextItem("!")
    font = bang.font()
    font.setPointSizeF(radius * 1.6)
    font.setBold(True)
    bang.setFont(font)
    bang.setBrush(QBrush(QColor(255, 255, 255)))
    bang.setZValue(1001)
    bang.setToolTip(tooltip)
    text_width = bang.boundingRect().width()
    text_height = bang.boundingRect().height()
    bang.setPos(qx - text_width / 2, qy - text_height / 2)
    gscene.addItem(bang)


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


def _swatch_icon(material: Material, size: int = 16) -> "QIcon":
    """A colored icon for `material`, via M4's `render_swatch()` (a flat
    PIL image) converted to a `QIcon` — "the designer chooses materials
    by appearance and name, never by hex code," per M4's own design
    intent, finally wired into the one place that still asked by name."""
    from PySide6.QtGui import QIcon, QImage, QPixmap

    from .materials import render_swatch

    img = render_swatch(material, size=size).convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimage = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()
    return QIcon(QPixmap.fromImage(qimage))


_RELATION_TYPE_LABELS: dict[str, str] = {
    "center_of": "Center Of",
    "mirror_of": "Mirror Of",
    "relative_to": "Relative To",
    "chord_of": "Chord Of",
}
_RELATION_CLASS_TO_KEY: dict[str, str] = {
    "CenterOf": "center_of",
    "MirrorOf": "mirror_of",
    "RelativeTo": "relative_to",
    "ChordOf": "chord_of",
}
# (param1 label, param2 label) — None hides that field. Matches the
# sibling keys set_relation()/schema.parse_relation() expect for each type.
_RELATION_PARAM_LABELS: dict[str | None, tuple[str | None, str | None]] = {
    None: (None, None),
    "center_of": (None, None),
    "mirror_of": ("About X", None),
    "relative_to": ("Offset X", "Offset Y"),
    "chord_of": ("Offset", "Angle (deg)"),
}


class PropertiesPanel(QWidget):
    """Rotate/scale/reassign-material/edit-relation for whatever's
    selected. The material field is a combo box with a swatch icon per
    entry, generated from the actual material, not just its name. The
    relation controls are generic (a type, a target, up to two numeric
    params relabeled per type) rather than four separate per-type forms —
    "a 'keep centred on firepit' checkbox, a mirror link," per M8's
    checklist, kept to one small control cluster."""

    def __init__(self, materials: MaterialLibrary, parent: QWidget | None = None):
        super().__init__(parent)
        self.id_label = QLabel("—")
        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setRange(-3600, 3600)
        self.rotation_spin.setSuffix("°")
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 100)
        self.scale_spin.setSingleStep(0.05)
        self.material_combo = QComboBox()
        for material_id, material in sorted(materials.materials.items(), key=lambda kv: kv[1].name):
            self.material_combo.addItem(_swatch_icon(material), material.name, userData=material_id)

        self.relation_type_combo = QComboBox()
        self.relation_type_combo.addItem("(none)", None)
        for key in RELATION_TYPES:
            self.relation_type_combo.addItem(_RELATION_TYPE_LABELS[key], key)
        self.relation_type_combo.currentIndexChanged.connect(self._update_relation_field_visibility)

        self.relation_target_combo = QComboBox()

        self.relation_param1_label = QLabel("Param 1")
        self.relation_param1_spin = QDoubleSpinBox()
        self.relation_param1_spin.setRange(-1000, 1000)
        self.relation_param2_label = QLabel("Param 2")
        self.relation_param2_spin = QDoubleSpinBox()
        self.relation_param2_spin.setRange(-1000, 1000)

        buttons = QHBoxLayout()
        self.apply_relation_button = QPushButton("Apply")
        self.clear_relation_button = QPushButton("Clear")
        buttons.addWidget(self.apply_relation_button)
        buttons.addWidget(self.clear_relation_button)

        layout = QFormLayout(self)
        layout.addRow("Object", self.id_label)
        layout.addRow("Rotation", self.rotation_spin)
        layout.addRow("Scale", self.scale_spin)
        layout.addRow("Material", self.material_combo)
        layout.addRow("Relation", self.relation_type_combo)
        layout.addRow("Target", self.relation_target_combo)
        layout.addRow(self.relation_param1_label, self.relation_param1_spin)
        layout.addRow(self.relation_param2_label, self.relation_param2_spin)
        layout.addRow(buttons)
        self.setEnabled(False)
        self._update_relation_field_visibility()

    def _update_relation_field_visibility(self) -> None:
        kind = self.relation_type_combo.currentData()
        label1, label2 = _RELATION_PARAM_LABELS.get(kind, (None, None))
        self.relation_target_combo.setVisible(kind is not None)
        self.relation_param1_label.setVisible(label1 is not None)
        self.relation_param1_spin.setVisible(label1 is not None)
        if label1:
            self.relation_param1_label.setText(label1)
        self.relation_param2_label.setVisible(label2 is not None)
        self.relation_param2_spin.setVisible(label2 is not None)
        if label2:
            self.relation_param2_label.setText(label2)

    def set_relation_targets(self, object_ids: list[str], exclude: str) -> None:
        current = self.relation_target_combo.currentText()
        self.relation_target_combo.blockSignals(True)
        self.relation_target_combo.clear()
        self.relation_target_combo.addItems(sorted(oid for oid in object_ids if oid != exclude))
        index = self.relation_target_combo.findText(current)
        self.relation_target_combo.setCurrentIndex(max(index, 0))
        self.relation_target_combo.blockSignals(False)

    def show_object(self, obj: SceneObject, all_object_ids: list[str]) -> None:
        self.id_label.setText(obj.id)
        widgets = (
            self.rotation_spin,
            self.scale_spin,
            self.material_combo,
            self.relation_type_combo,
            self.relation_target_combo,
            self.relation_param1_spin,
            self.relation_param2_spin,
        )
        for widget in widgets:
            widget.blockSignals(True)

        self.rotation_spin.setValue(obj.transform.rotation)
        self.scale_spin.setValue(obj.transform.scale)
        self.material_combo.setCurrentIndex(self.material_combo.findData(obj.material or ""))

        self.set_relation_targets(all_object_ids, exclude=obj.id)
        relation = obj.relation
        if relation is None:
            self.relation_type_combo.setCurrentIndex(0)
            self.relation_param1_spin.setValue(0)
            self.relation_param2_spin.setValue(0)
        else:
            key = _RELATION_CLASS_TO_KEY[type(relation).__name__]
            self.relation_type_combo.setCurrentIndex(self.relation_type_combo.findData(key))
            target_index = self.relation_target_combo.findText(relation.ref)
            self.relation_target_combo.setCurrentIndex(max(target_index, 0))
            if key == "mirror_of":
                self.relation_param1_spin.setValue(relation.about_x or relation.about_y or 0)
            elif key == "relative_to":
                self.relation_param1_spin.setValue(relation.dx)
                self.relation_param2_spin.setValue(relation.dy)
            elif key == "chord_of":
                self.relation_param1_spin.setValue(relation.offset)
                self.relation_param2_spin.setValue(relation.angle_deg)
        self._update_relation_field_visibility()

        for widget in widgets:
            widget.blockSignals(False)
        self.setEnabled(True)

    def clear(self) -> None:
        self.id_label.setText("—")
        self.setEnabled(False)


class EditorWindow(QMainWindow):
    """A thin Qt wrapper around `EditorSession`: this class owns widgets,
    draw calls, and event wiring; `self.session` owns the actual scene
    state and edit logic, and has no Qt dependency (see
    `editor_session.py`). Widget code reads `self.session.doc`/
    `.resolved`/`.violations` and calls `self.session.set_*()`/`.save()`
    rather than duplicating any of that here."""

    def __init__(
        self,
        materials_path: str | Path = "assets/materials.yaml",
        rules_path: str | Path | None = None,
    ):
        super().__init__()
        self.setWindowTitle("Landscape Editor")

        self.session = EditorSession(materials_path, rules_path)
        self._show_annotations = False
        self._selected_id: str | None = None
        self._hidden_layers: set[str] = set()
        self._layers_menu = None

        self._view = SceneGraphicsView()
        self._panel = PropertiesPanel(self.session.materials)
        self._panel.rotation_spin.valueChanged.connect(self._on_rotation_changed)
        self._panel.scale_spin.valueChanged.connect(self._on_scale_changed)
        self._panel.material_combo.currentIndexChanged.connect(self._on_material_changed)
        self._panel.apply_relation_button.clicked.connect(self._on_apply_relation)
        self._panel.clear_relation_button.clicked.connect(self._on_clear_relation)

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

        export_action = file_menu.addAction("&Export…")
        export_action.triggered.connect(self._on_export)

        edit_menu = self.menuBar().addMenu("&Edit")

        self._undo_action = edit_menu.addAction("&Undo")
        self._undo_action.setShortcut(QKeySequence.Undo)
        self._undo_action.triggered.connect(self._on_undo)

        self._redo_action = edit_menu.addAction("&Redo")
        self._redo_action.setShortcut(QKeySequence.Redo)
        self._redo_action.triggered.connect(self._on_redo)

        self._layers_menu = self.menuBar().addMenu("&Layers")

        create_menu = self.menuBar().addMenu("&Create")
        for kind in CREATABLE_PRIMITIVE_KINDS:
            action = create_menu.addAction(kind.replace("_", " ").title())
            action.triggered.connect(lambda checked=False, kind=kind: self._on_create_object(kind))

    def _on_create_object(self, kind: str) -> None:
        new_id = self.session.create_object(kind)
        self._rebuild_scene()
        # _rebuild_scene() just reselected whatever was selected before
        # this action (if anything) — clear that first so only the new
        # object ends up selected, not both.
        self._view.scene().clearSelection()
        self._select_item_by_id(new_id)

    def _rebuild_layers_menu(self) -> None:
        """(Re)builds the Layers menu from the loaded scene's layer list
        — only known once a scene is loaded, so this can't happen in
        `_build_menu` at construction time."""
        self._layers_menu.clear()
        for layer in self.session.doc.layers:
            action = self._layers_menu.addAction(layer)
            action.setCheckable(True)
            action.setChecked(layer not in self._hidden_layers)
            action.toggled.connect(lambda checked, layer=layer: self._on_layer_toggled(layer, checked))

    def _on_layer_toggled(self, layer: str, visible: bool) -> None:
        if visible:
            self._hidden_layers.discard(layer)
        else:
            self._hidden_layers.add(layer)
        self._rebuild_scene()

    def _on_undo(self) -> None:
        self.session.undo()
        self._rebuild_scene()

    def _on_redo(self) -> None:
        self.session.redo()
        self._rebuild_scene()

    def _on_export(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Rendered Scene", "", "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)"
        )
        if not path:
            return
        try:
            self.session.export(path, show_legend=True, show_annotations=self._show_annotations)
        except ValueError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported to {path}")

    def load_scene(self, scene_path: str | Path, show_annotations: bool = False) -> None:
        self.session.load(scene_path)
        self._show_annotations = show_annotations
        self._hidden_layers = set()
        self._rebuild_layers_menu()
        self._rebuild_scene()
        self._view.fitInView(self._view.scene().itemsBoundingRect(), Qt.KeepAspectRatio)
        self.setWindowTitle(f"Landscape Editor — {Path(scene_path).name}")

    def save_scene(self, path: str | Path | None = None) -> None:
        self.session.save(path)

    def _rebuild_scene(self) -> None:
        """Qt-side rebuild: ask the session to recompute geometry and
        violations, then turn that plain state into graphics items. The
        session has already done the actual work by the time this runs
        (`load_scene`/`_on_*_changed` call `session.load`/`set_*`, which
        call `session.recompute()` themselves)."""

        # setScene() below fires selectionChanged for the outgoing scene's
        # deselection, which would otherwise clobber self._selected_id to
        # None (via _on_selection_changed) before the reselect step runs.
        previously_selected = self._selected_id
        doc = self.session.doc
        gscene = build_graphics_scene(
            self.session.resolved,
            self.session.materials,
            doc.page_height,
            self._show_annotations,
            doc=doc,
            on_object_moved=self.session.sync_object,
            hidden_layers=self._hidden_layers,
            on_drag_start=self.session.push_undo,
            on_drag_end=self.session.autosave,
        )
        if self.session.rules:
            add_violation_overlays(gscene, self.session.violations, doc.page_height)
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
        self._update_status_bar()
        self._undo_action.setEnabled(self.session.can_undo)
        self._redo_action.setEnabled(self.session.can_redo)

    def _update_status_bar(self) -> None:
        if not self.session.rules:
            self.statusBar().clearMessage()
        elif self.session.violations:
            self.statusBar().showMessage(
                f"{len(self.session.violations)} rule violation(s) — hover a highlighted object for details"
            )
        else:
            self.statusBar().showMessage("No rule violations")

    def _select_item_by_id(self, object_id: str) -> None:
        for item in self._view.scene().items():
            if item.data(_OBJECT_ID_ROLE) == object_id:
                item.setSelected(True)
                return

    def _on_selection_changed(self) -> None:
        items = self._view.scene().selectedItems()
        if len(items) == 1 and isinstance(items[0], EditableItem):
            self._selected_id = items[0].scene_object.id
            all_ids = [o.id for o in self.session.doc.objects]
            self._panel.show_object(items[0].scene_object, all_ids)
        else:
            self._selected_id = None
            self._panel.clear()

    def _on_rotation_changed(self, value: float) -> None:
        if self._selected_id:
            self.session.set_rotation(self._selected_id, value)
            self._rebuild_scene()

    def _on_scale_changed(self, value: float) -> None:
        if self._selected_id:
            self.session.set_scale(self._selected_id, value)
            self._rebuild_scene()

    def _on_material_changed(self, index: int) -> None:
        material_id = self._panel.material_combo.itemData(index)
        if self._selected_id and material_id:
            self.session.set_material(self._selected_id, material_id)
            self._rebuild_scene()

    def _on_apply_relation(self) -> None:
        if not self._selected_id:
            return
        from PySide6.QtWidgets import QMessageBox

        kind = self._panel.relation_type_combo.currentData()
        if kind is None:
            self._on_clear_relation()
            return
        target = self._panel.relation_target_combo.currentText()
        if not target:
            QMessageBox.warning(self, "No target", "Pick a target object for this relation.")
            return

        params: dict[str, float] = {}
        if kind == "mirror_of":
            params["about_x"] = self._panel.relation_param1_spin.value()
        elif kind == "relative_to":
            params["dx"] = self._panel.relation_param1_spin.value()
            params["dy"] = self._panel.relation_param2_spin.value()
        elif kind == "chord_of":
            params["offset"] = self._panel.relation_param1_spin.value()
            params["angle_deg"] = self._panel.relation_param2_spin.value()

        try:
            self.session.set_relation(self._selected_id, kind, target, **params)
        except SchemaError as exc:
            QMessageBox.warning(self, "Invalid relation", str(exc))
            return
        self._rebuild_scene()

    def _on_clear_relation(self) -> None:
        if self._selected_id:
            self.session.set_relation(self._selected_id, None)
            self._rebuild_scene()
