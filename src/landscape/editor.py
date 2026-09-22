"""Graphical editor (M8) — every checklist item in TODO.md has landed here
in some real form; see that checklist for exactly what "landed" means for
each one (a few are honestly partial, e.g. resize/rotate handles only do
uniform scale/absolute rotation, not the whole design space M2 supports).

Landed: load a scene, show the same flat-mode picture `render_flat`
produces, pan/zoom, select/move/resize/rotate an object (drag directly on
the canvas via `EditableItem`/`SelectionHandle`, or the properties panel's
numeric fields), reassign its material by swatch, edit its relation
(center_of/mirror_of/relative_to/chord_of) via one generic control cluster,
create new objects from a palette of M2 primitives, save (Ctrl+S or
File > Save/Save As) back to disk losslessly, Ctrl+Z/Ctrl+Shift+Z undo/redo
(one snapshot per gesture, not per pixel), autosave to a `.autosave`
sidecar after every edit, layer visibility toggling, watch-and-reload for
external changes (auto-reload if nothing's unsaved, ask first if there
is), live rule-checker feedback (a marker + dashed highlight per violation,
closing M3b's last open item too), and File > Export… straight to
PNG/SVG/PDF.

Uses PySide6 (`QGraphicsScene`/`QGraphicsView`), per the UI-stack decision
recorded in TODO.md.

Every design object becomes its own `QGraphicsItem` (tagged with its scene
id via `setData(0, ...)`) so selection and dragging hit-test individual
objects rather than a flattened image. Annotations and keepout zones are
drawn but not made selectable/movable — they're derived/technical markers,
not primary design objects, at least for this slice.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QFileSystemWatcher, QPointF, Qt
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

# Visual redesign, phase 1 (2026-09-22): the editing canvas only — flat
# fills and lines, on request ("during editing, everything can just be
# basic fills and lines"). The textured/watercolor hi-fi look is a
# separate concern, M6's job, not this file's.
BACKGROUND_COLOR = QColor("#F6F1E4")  # warm off-white paper, not stark white
LINE_COLOR = QColor("#2B2A28")  # dark charcoal ("coal, like a pencil"), not flat black
TEXT_COLOR = QColor("#2B2A28")  # same charcoal for any text drawn over the canvas
LINE_WIDTH_PX = 3.0  # target on-screen stroke width for every shape, for now


def _line_width_for_zoom(zoom: float) -> float:
    """Scene-unit stroke width that renders at `LINE_WIDTH_PX` screen
    pixels at the given view zoom factor — "figure out what 3px is
    relative to total scale." Deliberately a plain (non-cosmetic) pen
    width, not a Qt cosmetic pen fixed at a constant device-pixel size:
    Rich asked for thickness that changes with magnification, i.e. one
    that scales up/down along with everything else as the view zooms
    (a cosmetic pen would instead stay a fixed 3px forever, regardless
    of zoom — the opposite of what was asked for). Recalibrated back to
    a true ~3px baseline on every scene rebuild (select, edit, undo,
    layer toggle, ...); continues to scale proportionally with any plain
    wheel-zoom in between, since that's just how a normal scene-space
    pen width behaves under `QGraphicsView`'s zoom transform."""
    return LINE_WIDTH_PX / (zoom or 1.0)


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
        centroid: QPointF,
        on_moved: Callable[[str], None] | None = None,
        on_drag_start: Callable[[], None] | None = None,
        on_drag_end: Callable[[], None] | None = None,
    ):
        super().__init__(path)
        self.scene_object = scene_object
        # Shapely's true centroid (in this item's Qt/y-flipped coordinates),
        # not the bounding-box center: `geometry._apply_transform` pivots
        # scale/rotation about `origin="centroid"`, and for any asymmetric
        # shape (an L-shaped walkway, a bent fence_line, an irregular
        # polygon) the bbox center and the centroid are different points.
        # SelectionHandle must pivot its live preview about this same point
        # or the object visibly jumps the instant a rotate/resize commits.
        self.centroid = centroid
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
                self.centroid += delta  # translation shifts the centroid by the same delta
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


class SelectionHandle(QGraphicsEllipseItem):
    """A small draggable handle for resizing (uniform scale about the
    target's centroid — `Transform.scale` is a single uniform factor,
    not independent width/height) or rotating a selected `EditableItem`
    directly on the canvas, not just via the properties panel.

    The live preview never touches the document — only a Qt-level item
    transform — so there's nothing to snapshot for undo until the single
    commit on release. `on_drag_end` is wired straight to
    `EditorSession.set_scale`/`set_rotation`, the same calls the
    properties panel's spinboxes already make, which each do exactly one
    `push_undo()` + mutate + sync + recompute + autosave — "one undo
    entry per gesture," satisfied for free rather than needing this class
    to also bracket a gesture of its own.

    Deliberately does *not* trigger a scene rebuild during or right after
    the drag: `_rebuild_scene()` throws away the whole `QGraphicsScene`,
    which would destroy this handle while it's still processing its own
    mouse event — the same class of hazard as the segfault found earlier
    in this project (an object destroyed while code still holds a live
    reference to it). The live-preview transform stays as the visual
    representation — already correct — until some *other* action
    triggers the next rebuild, which then regenerates the authoritative
    path from the committed value. `EditableItem`'s own move-drag follows
    the same "commit, don't rebuild" precedent already.

    Resize sensitivity is deliberately *not* a ratio of raw scene-space
    distances (`new_distance / starting_distance`) — a real bug found by
    actually using it: dragging a thin, wide object like a deck panel
    sideways could blow its scale up hugely, and the same drag felt far
    more sensitive when the view was zoomed out. Two compounding causes:
    Qt hands `itemChange` mouse positions already converted to scene
    coordinates, so the same physical drag corresponds to a *larger*
    scene-space distance the further the view is zoomed out; and a ratio
    divides by `starting_distance`, which is small for small/thin
    objects, amplifying the same absolute drag into a huge factor. Using
    an additive, zoom-normalized delta with a hard per-gesture clamp
    (`_MAX_GESTURE_FACTOR`) fixes both: the same physical drag produces
    the same scale change regardless of the object's size or the current
    zoom, and no single gesture can blow the scale past a fixed multiple
    no matter how far or fast the mouse moves. Rotation doesn't have this
    problem — an angle from the centroid is scale-invariant under uniform
    zoom, since zoom scales both dx and dy equally — so it keeps its
    original angle-delta approach."""

    RADIUS = 0.3
    RESIZE_SENSITIVITY = 0.01  # scale change per zoom-normalized scene unit dragged
    MAX_GESTURE_FACTOR = 4.0  # a single gesture can at most 4x or quarter the scale

    def __init__(
        self,
        kind: str,  # "resize" | "rotate"
        target: EditableItem,
        view: "SceneGraphicsView",
        on_drag_end: Callable[[float], None] | None,
    ):
        super().__init__(-self.RADIUS, -self.RADIUS, self.RADIUS * 2, self.RADIUS * 2)
        self.kind = kind
        self.target = target
        self.view = view
        self._on_drag_end = on_drag_end
        color = QColor(30, 120, 220) if kind == "resize" else QColor(220, 140, 20)
        self.setBrush(QBrush(color))
        self.setPen(QPen(color.darker(150), 0.04))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(2000)
        self.setToolTip("Drag to resize" if kind == "resize" else "Drag to rotate")
        self._dragging = False
        self._center = target.centroid  # refreshed at each gesture's start too
        self._start_pos = None
        self._start_angle = 0.0
        self._start_scale = 1.0
        self._start_rotation = 0.0
        self._final_value: float | None = None
        self._press_scene_pos = QPointF()
        self._press_item_pos = QPointF()

    def mousePressEvent(self, event) -> None:
        """Deliberately doesn't call `super()`/rely on `QGraphicsItem`'s
        own default drag handling — a real, confirmed bug (only found by
        driving this with genuine `QTest` mouse events, not the
        `setPos()`-based tests that predate this): Qt's default
        `mouseMoveEvent` for a *movable* item, when the scene has a
        selection, moves that *whole selection* together with whatever
        item you happen to be dragging — even one, like this handle,
        that isn't itself selected. Since the target object stays
        selected the entire time its handles are shown, dragging a
        handle silently dragged the selected object too, corrupting its
        position underneath the resize/rotate preview. Tracking the
        press/move ourselves and calling `setPos()` directly (still
        routed through `itemChange` below via `ItemSendsGeometryChanges`)
        sidesteps that "move the whole selection" behavior entirely."""
        self._press_scene_pos = event.scenePos()
        self._press_item_pos = self.pos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        delta = event.scenePos() - self._press_scene_pos
        self.setPos(self._press_item_pos + delta)
        event.accept()

    def _distance(self, pos) -> float:
        return math.hypot(pos.x() - self._center.x(), pos.y() - self._center.y())

    def _angle(self, pos) -> float:
        return math.degrees(math.atan2(pos.y() - self._center.y(), pos.x() - self._center.x()))

    def _zoom(self) -> float:
        """The view's current horizontal scale factor (its wheelEvent
        always scales x/y together, so this alone represents zoom)."""
        return self.view.transform().m11() or 1.0

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            if not self._dragging:
                # A fresh gesture: re-read the target's *current* state,
                # not whatever this handle was constructed with — a plain
                # move-drag on the object deliberately doesn't rebuild the
                # scene (see EditableItem), so it never recreates this
                # handle either. Without refreshing _center here too, a
                # move followed by a resize/rotate (without reselecting
                # in between) would scale/rotate about the object's
                # *pre-move* center — a real bug: the object would visibly
                # swing to a new position instead of turning in place.
                self._dragging = True
                self._center = self.target.centroid
                self._start_scale = self.target.scene_object.transform.scale
                self._start_rotation = self.target.scene_object.transform.rotation
                self._start_pos = self.pos()
                self._start_angle = self._angle(self.pos())
            self.target.setTransformOriginPoint(self._center)
            if self.kind == "resize":
                scene_delta = self._distance(value) - self._distance(self._start_pos)
                screen_equivalent_delta = scene_delta * self._zoom()
                raw_scale = self._start_scale + screen_equivalent_delta * self.RESIZE_SENSITIVITY
                clamped = min(
                    max(raw_scale, self._start_scale / self.MAX_GESTURE_FACTOR),
                    self._start_scale * self.MAX_GESTURE_FACTOR,
                )
                self._final_value = max(0.01, clamped)
                self.target.setScale(self._final_value / self._start_scale)
            else:
                delta_angle = self._angle(value) - self._start_angle
                self._final_value = self._start_rotation + delta_angle
                self.target.setRotation(delta_angle)
            return value
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:
        # No super() call here either — see mousePressEvent's docstring;
        # this handler fully owns press/move/release, so there's no base
        # class drag state left to hand off to.
        event.accept()
        self.end_drag()

    def end_drag(self) -> None:
        """The actual commit, split out from `mouseReleaseEvent` so it's
        directly callable without a real Qt mouse event — the same
        testability gap `EditableItem` doesn't have (its commit happens
        entirely in `itemChange`, driven by plain `setPos()` calls)."""
        if self._dragging:
            self._dragging = False
            if self._final_value is not None and self._on_drag_end:
                self._on_drag_end(self._final_value)


def _add_material_item(
    scene: QGraphicsScene,
    obj: ResolvedObject,
    material: Material,
    page_height: float,
    line_width: float = 0.2,
    scene_object: SceneObject | None = None,
    on_moved: Callable[[str], None] | None = None,
    on_drag_start: Callable[[], None] | None = None,
    on_drag_end: Callable[[], None] | None = None,
) -> QGraphicsPathItem:
    """`line_width` (scene units) is deliberately the same fixed, dark
    charcoal outline for every shape here, regardless of the material's
    own `edge` weight/color — a temporary simplification for the "basic
    fills and lines" editing look Rich asked for, not a permanent
    replacement for material-specific edge styling. `render_flat` (the
    real M5/M6 renderer, and what `EditorSession.export()` calls) is
    untouched and still uses each material's actual edge weight/color."""
    path = _path_for_geometry(obj.geometry, page_height)
    if scene_object is not None:
        c = obj.geometry.centroid
        centroid = QPointF(c.x, page_height - c.y)  # same y-flip _path_for_geometry uses
        item: QGraphicsPathItem = EditableItem(path, scene_object, centroid, on_moved, on_drag_start, on_drag_end)
    else:
        item = QGraphicsPathItem(path)
        item.setData(_OBJECT_ID_ROLE, obj.id)

    fill = QColor(material.color)
    is_area = obj.geometry.geom_type in ("Polygon", "MultiPolygon")

    item.setBrush(QBrush(fill) if is_area else QBrush(Qt.NoBrush))
    item.setPen(QPen(LINE_COLOR, line_width))
    scene.addItem(item)
    return item


def _add_annotation_item(
    scene: QGraphicsScene, obj: ResolvedObject, label: str, page_height: float, line_width: float = 0.2
) -> None:
    """Annotations and keepout zones: dashed outline, no fill, a text
    label at the centroid — mirrors `render_flat._draw_annotation`. Not
    selectable/movable in this slice."""
    path = _path_for_geometry(obj.geometry, page_height)
    item = QGraphicsPathItem(path)
    item.setData(_OBJECT_ID_ROLE, obj.id)
    pen = QPen(LINE_COLOR)
    pen.setStyle(Qt.DashLine)
    pen.setWidthF(line_width)
    item.setPen(pen)
    item.setBrush(QBrush(Qt.NoBrush))
    scene.addItem(item)

    centroid = obj.geometry.centroid
    text = QGraphicsSimpleTextItem(label)
    text.setBrush(QBrush(TEXT_COLOR))
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
    line_width: float = 0.2,
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
    since there's only flat mode to toggle to until M6 exists.
    `line_width` (scene units) is the uniform outline width for every
    shape — see `_line_width_for_zoom`, which callers use to convert a
    target screen-pixel width into this. Default here is just a sane
    fallback for callers (mostly tests) that don't care about zoom."""
    gscene = QGraphicsScene()
    gscene.setBackgroundBrush(QBrush(BACKGROUND_COLOR))
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
            _add_annotation_item(gscene, obj, label, page_height, line_width)
            continue
        material = materials.resolve(obj.material)
        scene_object = doc.get(obj.id) if doc is not None else None
        _add_material_item(
            gscene, obj, material, page_height, line_width, scene_object, on_object_moved, on_drag_start, on_drag_end
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
    only active while space is down.

    Zoom anchors on the selected object's center when exactly one object
    is selected — the same fixed, predictable origin `SelectionHandle`
    already rotates/resizes about — or the viewport center otherwise.
    Deliberately not `AnchorUnderMouse`: that anchor point depends on
    incidental mouse position, which is the opposite of "the same origin
    as the rotation axis." `setTransformationAnchor` only offers
    "under the mouse" or "view center," neither of which is "the
    selected object," so this computes the correction manually: note the
    anchor's viewport pixel position, scale, then scroll to put that
    scene point back at the same pixel."""

    ZOOM_PER_TICK = 1.05  # was 1.15; that felt too aggressive per scroll tick

    def __init__(self, scene: QGraphicsScene | None = None):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)  # anchoring is handled manually below
        # Covers the viewport area outside the scene's own background
        # (e.g. once panned/zoomed past the drawing's edge) with the same
        # off-white paper tone, so there's no stark-white gap at the edges.
        self.setBackgroundBrush(QBrush(BACKGROUND_COLOR))

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = self.ZOOM_PER_TICK if event.angleDelta().y() > 0 else 1 / self.ZOOM_PER_TICK
        self._scale_anchored_at(factor, self._zoom_anchor_point())

    def _zoom_anchor_point(self) -> QPointF:
        scene = self.scene()
        if scene is not None:
            selected = scene.selectedItems()
            if len(selected) == 1:
                return selected[0].sceneBoundingRect().center()
        return self.mapToScene(self.viewport().rect().center())

    def _scale_anchored_at(self, factor: float, scene_point: QPointF) -> None:
        viewport_pos_before = self.mapFromScene(scene_point)
        self.scale(factor, factor)
        viewport_pos_after = self.mapFromScene(scene_point)
        delta = viewport_pos_after - viewport_pos_before
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(h.value() + round(delta.x()))
        v.setValue(v.value() + round(delta.y()))

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
        self._selection_handles: list[SelectionHandle] = []
        self._last_known_mtime_ns: int | None = None
        self._file_watcher = QFileSystemWatcher()
        self._file_watcher.fileChanged.connect(self._on_file_changed_externally)
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
        # "Drag/rotate" tooltips (SelectionHandle.setToolTip) and status
        # bar messages (export/reload/violation counts) are the only
        # popup-style text that exists today — dark, on request, and
        # explicitly regardless of the OS's own light/dark theme default.
        self.setStyleSheet(
            f"QToolTip {{ color: {LINE_COLOR.name()}; background-color: {BACKGROUND_COLOR.name()}; "
            f"border: 1px solid {LINE_COLOR.name()}; }}"
            f"QStatusBar {{ color: {LINE_COLOR.name()}; }}"
        )

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
        # fitInView() just changed the view's zoom, but the scene built
        # a moment ago baked its line widths in for the *old* (identity)
        # zoom — rebuild once more now that the real fitted zoom is
        # known, so lines start out at the intended ~3px, not whatever
        # `LINE_WIDTH_PX / 1.0` happened to look like on this scene.
        self._rebuild_scene()
        self.setWindowTitle(f"Landscape Editor — {Path(scene_path).name}")
        self._watch_scene_file()

    def save_scene(self, path: str | Path | None = None) -> None:
        self.session.save(path)
        self._remember_own_write()

    def _watch_scene_file(self) -> None:
        """(Re)point the file watcher at the just-loaded scene, and
        record its mtime so a later `fileChanged` signal caused by our
        *own* save/autosave can be told apart from a genuine external
        edit — see `_on_file_changed_externally`."""
        watched = self._file_watcher.files()
        if watched:
            self._file_watcher.removePaths(watched)
        self._file_watcher.addPath(str(self.session.scene_path))
        self._remember_own_write()

    def _remember_own_write(self) -> None:
        path = self.session.scene_path
        if path and path.exists():
            self._last_known_mtime_ns = path.stat().st_mtime_ns

    def _on_file_changed_externally(self, path: str) -> None:
        changed = Path(path)
        # Some editors/tools save via temp-file-plus-rename, which drops
        # the underlying OS watch after the first change; re-add so the
        # same logical file keeps being watched.
        if changed.exists() and path not in self._file_watcher.files():
            self._file_watcher.addPath(path)
        if not changed.exists():
            return  # e.g. a temp-file-plus-rename's intermediate delete

        if changed.stat().st_mtime_ns == self._last_known_mtime_ns:
            return  # this change was our own save()/autosave(), already accounted for

        if not self.session.dirty:
            self.load_scene(changed, show_annotations=self._show_annotations)
            self.statusBar().showMessage(f"Reloaded {changed.name} (changed on disk)")
            return

        from PySide6.QtWidgets import QMessageBox

        choice = QMessageBox.question(
            self,
            "File changed on disk",
            f"'{changed.name}' was changed outside the editor, and you have unsaved edits.\n\n"
            "Reload it and discard your changes?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice == QMessageBox.Yes:
            self.load_scene(changed, show_annotations=self._show_annotations)
            self.statusBar().showMessage(f"Reloaded {changed.name} (changed on disk)")

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
        zoom = self._view.transform().m11() or 1.0
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
            line_width=_line_width_for_zoom(zoom),
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
            self._update_selection_handles(items[0])
        else:
            self._selected_id = None
            self._panel.clear()
            self._update_selection_handles(None)

    def _update_selection_handles(self, target: EditableItem | None) -> None:
        for handle in self._selection_handles:
            try:
                scene = handle.scene()
                if scene is not None:
                    scene.removeItem(handle)
            except RuntimeError:
                # The C++ object behind a previous gesture's handle may
                # already be gone if a full rebuild replaced the whole
                # scene since — see the module docstring on why handles
                # never trigger a rebuild themselves, but something else
                # (a panel edit, undo/redo, layer toggle) always can.
                pass
        self._selection_handles = []

        if target is None:
            return

        rect = target.path().boundingRect()
        resize_handle = SelectionHandle("resize", target, self._view, self._on_handle_resized)
        resize_handle.setPos(rect.topRight())
        rotate_handle = SelectionHandle("rotate", target, self._view, self._on_handle_rotated)
        margin = max(rect.height() * 0.15, 0.5)
        rotate_handle.setPos(rect.center().x(), rect.top() - margin)

        scene = self._view.scene()
        scene.addItem(resize_handle)
        scene.addItem(rotate_handle)
        self._selection_handles = [resize_handle, rotate_handle]

    def _on_handle_resized(self, value: float) -> None:
        if not self._selected_id:
            return
        self.session.set_scale(self._selected_id, value)
        self._panel.scale_spin.blockSignals(True)
        self._panel.scale_spin.setValue(value)
        self._panel.scale_spin.blockSignals(False)

    def _on_handle_rotated(self, value: float) -> None:
        if not self._selected_id:
            return
        self.session.set_rotation(self._selected_id, value)
        self._panel.rotation_spin.blockSignals(True)
        self._panel.rotation_spin.setValue(value)
        self._panel.rotation_spin.blockSignals(False)

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
