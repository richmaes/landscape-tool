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

from PySide6.QtCore import QFileSystemWatcher, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shapely.geometry.base import BaseGeometry

from .editor_session import CREATABLE_PRIMITIVE_KINDS, RELATION_TYPES, EditorSession
from .geometry import ResolvedObject, ResolvedScene
from .materials import Material, MaterialLibrary
from .render import EXTENSIONS as EXPORT_EXTENSIONS
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
        outline_hit_width: float | None = None,
    ):
        super().__init__(path)
        self.scene_object = scene_object
        # Set for the dashed, unfilled objects (annotations, keepouts):
        # only a band this wide along the outline is clickable, so their
        # empty interior doesn't steal clicks from whatever sits inside
        # them (the hot tub inside the ground-cover box, the firepit
        # inside its keepout). See `shape()`.
        self._outline_hit_width = outline_hit_width
        self.joints_item: QGraphicsPathItem | None = None  # paver joints, if the material is a paver
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
        self._last_scene_pos = QPointF()
        self.setData(_OBJECT_ID_ROLE, scene_object.id)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def shape(self) -> QPainterPath:
        if self._outline_hit_width is None:
            return super().shape()
        stroker = QPainterPathStroker()
        stroker.setWidth(self._outline_hit_width)
        return stroker.createStroke(self.path())

    def boundingRect(self):
        # The hit band extends past the drawn pen; Qt only hit-tests
        # within boundingRect(), so it has to cover the whole band.
        if self._outline_hit_width is None:
            return super().boundingRect()
        return super().boundingRect().united(self.shape().boundingRect())

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
                for child in self.childItems():  # e.g. an annotation's label
                    # pos() never changes (vetoed below), so children
                    # don't follow on their own — move them explicitly.
                    child.moveBy(delta.x(), delta.y())
                if self._on_moved:
                    self._on_moved(self.scene_object.id)
            return self.pos()  # veto Qt's own pos(); the path already moved
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        """Deliberately doesn't call `super()`/rely on `QGraphicsItem`'s
        own default drag handling — a real, confirmed bug (found the same
        way as `SelectionHandle`'s "drags the whole selection" bug: a
        genuine multi-step `QTest` mouse drag, not a single `setPos()`
        jump). Qt's default `mouseMoveEvent`, on every move event,
        recomputes the new position as `press-time pos() + (current
        mouse scenePos - press-time mouse scenePos)` — the *cumulative*
        offset since press, using its own cached `pos()` as the
        reference. But `itemChange` above always vetoes `pos()` back to
        its original (frozen) value, since this class deliberately
        tracks position via `scene_object.transform`/the path instead
        of Qt's own `pos()`. So on the *second* move event onward, Qt
        recomputes that same cumulative offset from the same frozen
        reference, and `itemChange`'s `delta = value - self.pos()`
        reads that whole cumulative amount as if it were just this one
        event's incremental step — applying the growing cumulative
        total again on top of what's already been applied, every single
        event. A real continuous drag (many small move events, the way
        an actual mouse produces them) compounds this every step,
        producing exactly what Rich reported: the object "accelerates
        beyond the cursor." A single-jump test (press once, one big
        move, release) never triggers this, since there's no *second*
        event during which the compounding could show up — the same
        reason `SelectionHandle`'s bug needed a real, driven mouse
        gesture to catch, not `setPos()`. Fixed by tracking the mouse's
        own last scene position ourselves and always feeding
        `itemChange` a true incremental, per-event delta, independent of
        whatever `pos()` Qt itself believes this item is at."""
        self._last_scene_pos = event.scenePos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        delta = event.scenePos() - self._last_scene_pos
        self._last_scene_pos = event.scenePos()
        self.setPos(self.pos() + delta)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        # A real, confirmed bug: mousePressEvent/mouseMoveEvent above
        # deliberately skip `super()` (see mousePressEvent's docstring),
        # but click-to-select turns out to live in the *default*
        # `mouseReleaseEvent`'s own body, not at scene-dispatch/press
        # time as it's easy to assume — skipping `super()` here too, as
        # a first pass did, silently broke selecting an object by
        # clicking it (confirmed: `isSelected()` stayed `False` after a
        # real `QTest.mouseClick`, and with it, the resize/rotate
        # handles never appeared, since they're only ever added in
        # response to a `selectionChanged` signal that now never fired).
        # Calling `super()` here does NOT reintroduce the "drags the
        # whole selection" bug that motivated skipping the default
        # mousePressEvent/mouseMoveEvent in the first place — that bug
        # lived specifically in the default mouseMoveEvent's body, which
        # this class still never calls.
        super().mouseReleaseEvent(event)
        if self._dragging:
            self._dragging = False
            if self._on_drag_end:
                self._on_drag_end()


def dimensions_text(geom: BaseGeometry, factor: float = 1.0, units: str = "ft") -> str:
    """A selected object's real size, for the properties panel: its tightest
    (rotated) bounding rectangle, so a turned 6 x 4 shed still reads
    6.00 x 4.00 rather than the larger axis-aligned box around it. Circles
    read as a diameter, plain lines as a length. `factor` scales the result
    — the live preview while a resize handle is being dragged."""
    if geom.is_empty:
        return "—"
    if geom.geom_type in ("LineString", "MultiLineString"):
        return f"{geom.length * factor:.2f} {units} long"
    # Shapely's own envelope maths divides by zero on perfectly vertical or
    # horizontal edges and then handles it; the result is right, only the
    # numpy warning is noise.
    import numpy as np

    with np.errstate(divide="ignore", invalid="ignore"):
        rect = geom.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    sides = sorted(
        (math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2)), reverse=True
    )
    long_side, short_side = sides[0] * factor, sides[1] * factor
    area = geom.area * factor * factor
    if long_side and abs(long_side - short_side) / long_side < 0.01 and abs(area - math.pi * long_side**2 / 4) / area < 0.02:
        return f"⌀ {long_side:.2f} {units}"
    return f"{long_side:.2f} × {short_side:.2f} {units}"


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
        on_preview: Callable[[float], None] | None = None,
    ):
        super().__init__(-self.RADIUS, -self.RADIUS, self.RADIUS * 2, self.RADIUS * 2)
        self.kind = kind
        self.target = target
        self.view = view
        self._on_drag_end = on_drag_end
        # Called on every step of a resize gesture with the scale factor so
        # far relative to the gesture's start — for live readouts (the
        # panel's Size row), before anything is committed.
        self._on_preview = on_preview
        color = QColor(30, 120, 220) if kind == "resize" else QColor(220, 140, 20)
        self.setBrush(QBrush(color))
        self.setPen(QPen(color.darker(150), 0.04))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(2000)
        self.setToolTip("Drag to resize" if kind == "resize" else "Drag to rotate")
        self._dragging = False
        self._placing = False
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

    def place_at(self, pos: QPointF) -> None:
        """Move the handle without it counting as a drag — `setPos()`
        alone would run `itemChange` below and start a fresh
        resize/rotate gesture."""
        self._placing = True
        try:
            self.setPos(pos)
        finally:
            self._placing = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None and not self._placing:
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
                if self._on_preview:
                    self._on_preview(self._final_value / self._start_scale)
            else:
                delta_angle = self._angle(value) - self._start_angle
                # `delta_angle` is measured in Qt's y-down coordinates
                # (positive = clockwise on screen, which is also what
                # `setRotation` expects), but `transform.rotation` feeds
                # Shapely's `affinity.rotate` in the scene's y-up
                # coordinates (positive = counter-clockwise) — so the
                # committed value takes the opposite sign. Adding it
                # unchanged, as this once did, committed the mirror image
                # of the preview, and the object flipped on the next rebuild.
                self._final_value = self._start_rotation - delta_angle
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
    units: str = "ft",
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
    joints = _paver_joints_path(obj.geometry, material, obj.pattern, page_height, units)
    if joints is not None:
        joints_item = QGraphicsPathItem(joints, item)
        joints_item.setPen(QPen(QColor(material.color).darker(135), line_width * 0.25))
        joints_item.setAcceptedMouseButtons(Qt.NoButton)
        if isinstance(item, EditableItem):
            item.joints_item = joints_item
    scene.addItem(item)
    return item


def _paver_joints_path(geom: BaseGeometry, material: Material, pattern: str | None, page_height: float,
                       units: str) -> QPainterPath | None:
    """Every brick outline of a paver object (see pavers.py), or None."""
    from shapely.geometry import MultiPolygon

    from .pavers import bricks_for, paver_spec

    spec = paver_spec(material, pattern, units)
    if spec is None:
        return None
    bricks = bricks_for(geom, spec)
    return _path_for_geometry(MultiPolygon(bricks), page_height) if bricks else None


def _add_annotation_item(
    scene: QGraphicsScene,
    obj: ResolvedObject,
    label: str,
    page_height: float,
    line_width: float = 0.2,
    scene_object: SceneObject | None = None,
    on_moved: Callable[[str], None] | None = None,
    on_drag_start: Callable[[], None] | None = None,
    on_drag_end: Callable[[], None] | None = None,
) -> None:
    """Annotations and keepout zones: dashed outline, no fill, a text
    label at the centroid — mirrors `render_flat._draw_annotation`.

    With a `scene_object`, selectable/movable/resizable/rotatable like
    any other object (Rich couldn't select the firepit keepout or the
    ground-cover box around the deck), but clickable only along the
    outline — see `EditableItem.shape()`. The hit band is a few times the
    drawn line width, so it's easy to grab without being much wider than
    the line itself on screen."""
    path = _path_for_geometry(obj.geometry, page_height)
    if scene_object is not None:
        c = obj.geometry.centroid
        centroid = QPointF(c.x, page_height - c.y)
        item: QGraphicsPathItem = EditableItem(
            path, scene_object, centroid, on_moved, on_drag_start, on_drag_end, outline_hit_width=line_width * 3
        )
    else:
        item = QGraphicsPathItem(path)
        item.setData(_OBJECT_ID_ROLE, obj.id)
    pen = QPen(LINE_COLOR)
    pen.setStyle(Qt.DashLine)
    pen.setWidthF(line_width)
    item.setPen(pen)
    item.setBrush(QBrush(Qt.NoBrush))
    scene.addItem(item)

    centroid = obj.geometry.centroid
    # A child of the outline, so it travels with it when dragged (see
    # EditableItem.itemChange) — and never takes clicks itself, so it
    # can't block whatever is under it.
    text = QGraphicsSimpleTextItem(label, item)
    text.setAcceptedMouseButtons(Qt.NoButton)
    text.setBrush(QBrush(TEXT_COLOR))
    font = text.font()
    font.setPointSizeF(0.8)
    text.setFont(font)
    text.setPos(centroid.x, page_height - centroid.y)


class OverlayItem(QGraphicsPathItem):
    """The legend box or the scale indicator on the design canvas: drawn
    from `overlays.py`'s layout, dragged by the designer, and committed to
    the document as a new origin point on release (`on_moved(name, x, y)`,
    scene units, +y north).

    Owns its press/move/release rather than using Qt's default drag, which
    would also drag whatever object happens to be selected — the same trap
    `SelectionHandle` hit. And like `EditableItem`, it never triggers a
    scene rebuild mid-gesture: it just stays where it was dropped until the
    next rebuild redraws it from the committed position. Its own path is
    the small origin marker; everything else is child items."""

    MARKER = 0.12  # origin marker radius, scene units

    def __init__(self, name: str, origin_x: float, origin_y: float, page_height: float,
                 on_moved: Callable[[str, float, float], None] | None):
        marker = QPainterPath()
        qx, qy = origin_x, page_height - origin_y
        marker.addEllipse(QPointF(qx, qy), self.MARKER, self.MARKER)
        marker.moveTo(qx - self.MARKER * 2, qy)
        marker.lineTo(qx + self.MARKER * 2, qy)
        marker.moveTo(qx, qy - self.MARKER * 2)
        marker.lineTo(qx, qy + self.MARKER * 2)
        super().__init__(marker)
        self.name = name
        self.origin = QPointF(origin_x, origin_y)
        self._on_moved = on_moved
        self._press_scene_pos = QPointF()
        self._press_item_pos = QPointF()
        self.setPen(QPen(QColor(30, 120, 220), 0.03))
        self.setZValue(5000)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag to move (its origin is the blue marker)")

    def _marker_rect(self):
        # not super().boundingRect(): for a path item with a pen, Qt's own
        # boundingRect() calls the virtual shape() — which is overridden
        # below in terms of this, an infinite recursion
        return self.path().boundingRect().adjusted(-0.05, -0.05, 0.05, 0.05)

    def shape(self) -> QPainterPath:
        # grab it anywhere on the box/line, not just on the tiny marker
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def boundingRect(self):
        return self.childrenBoundingRect().united(self._marker_rect())

    def mousePressEvent(self, event) -> None:
        self._press_scene_pos = event.scenePos()
        self._press_item_pos = self.pos()
        self.setCursor(Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self.setPos(self._press_item_pos + (event.scenePos() - self._press_scene_pos))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.setCursor(Qt.OpenHandCursor)
        event.accept()
        moved = self.pos() - self._press_item_pos
        if (moved.x() or moved.y()) and self._on_moved:
            # the item's pos is an offset from where it was built; +y north is Qt -y
            self._on_moved(self.name, self.origin.x() + self.pos().x(), self.origin.y() - self.pos().y())


_OVERLAY_FONT_PX = 100  # see _overlay_text


def _overlay_text(parent: QGraphicsItem, text: str, size: float, x: float, baseline_qt_y: float) -> None:
    """Text `size` scene units tall (em), with its baseline at
    `baseline_qt_y`. Qt clamps fractional point sizes (a 0.25 pt label came
    out ~15 ft tall), so the font is set in whole pixels — which item
    coordinates use directly — and the item is scaled down to size."""
    item = QGraphicsSimpleTextItem(text, parent)
    font = item.font()
    font.setPixelSize(_OVERLAY_FONT_PX)
    item.setFont(font)
    item.setBrush(QBrush(TEXT_COLOR))
    k = size / _OVERLAY_FONT_PX
    item.setScale(k)
    item.setPos(x, baseline_qt_y - QFontMetricsF(font).ascent() * k)


def add_overlay_items(
    gscene: QGraphicsScene,
    doc: SceneDocument,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    line_width: float,
    hidden_layers: set[str] | None = None,
    on_moved: Callable[[str, float, float], None] | None = None,
) -> dict[str, "OverlayItem"]:
    """The drawing's legend box and scale indicator, as draggable canvas
    items, laid out by `overlays.py` exactly as the renderers draw them.
    Returns them by name."""
    from .overlays import legend_entries, legend_layout, scale_indicator_layout

    h = doc.page_height
    # thinner than the drawing's outlines: legend swatches are small, and a
    # full-weight outline swamps their color
    pen = QPen(LINE_COLOR, line_width * 0.35)

    legend = legend_layout(doc, legend_entries(scene, materials, hidden_layers or ()))
    box = OverlayItem("legend", legend.x, legend.y, h, on_moved)
    frame = QGraphicsRectItem(legend.x, h - legend.y, legend.width, legend.height, box)
    frame.setBrush(QBrush(BACKGROUND_COLOR))
    frame.setPen(pen)
    _overlay_text(box, legend.title, legend.title_size, legend.title_x, h - legend.title_baseline_y)
    for row in legend.rows:
        top = h - row.swatch_y
        if row.entry.shape == "square":
            swatch = QGraphicsRectItem(row.swatch_x, top, row.swatch, row.swatch, box)
        else:
            swatch = QGraphicsEllipseItem(row.swatch_x, top, row.swatch, row.swatch, box)
        swatch.setBrush(QBrush(QColor(row.entry.color)) if row.entry.color else QBrush(BACKGROUND_COLOR))
        swatch.setPen(pen)
        _overlay_text(box, row.entry.label, legend.text_size, row.text_x, h - row.baseline_y)
    gscene.addItem(box)

    bar = scale_indicator_layout(doc)
    indicator = OverlayItem("scale_indicator", bar.x, bar.y, h, on_moved)
    line = QPainterPath()
    y = h - bar.y
    line.moveTo(bar.x, y - bar.tick)
    line.lineTo(bar.x, y)
    line.lineTo(bar.x + bar.length, y)
    line.lineTo(bar.x + bar.length, y - bar.tick)
    stroke = QGraphicsPathItem(line, indicator)
    stroke.setPen(QPen(LINE_COLOR, line_width * 1.3))
    _overlay_text(indicator, bar.label, bar.text_size, bar.label_x, h - bar.label_baseline_y)
    gscene.addItem(indicator)
    return {"legend": box, "scale_indicator": indicator}


class CameraMarker(QGraphicsPathItem):
    """One end of a 3D camera on the design canvas: the eye (where the
    viewer stands) or the look-at point. Dragged like the legend — its own
    press/move/release, so a drag never also moves the selected object —
    with the rig's line and view wedge following live; the new position is
    committed on release."""

    RADIUS = 0.35

    def __init__(self, rig: "CameraRig", role: str, x: float, y: float):
        path = QPainterPath()
        qx, qy = x, rig.page_height - y
        if role == "eye":
            path.addEllipse(QPointF(qx, qy), self.RADIUS, self.RADIUS)
            path.addEllipse(QPointF(qx, qy), self.RADIUS * 0.35, self.RADIUS * 0.35)
        else:  # a crosshair: "look here"
            r = self.RADIUS
            path.addEllipse(QPointF(qx, qy), r * 0.6, r * 0.6)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                path.moveTo(qx + dx * r * 0.6, qy + dy * r * 0.6)
                path.lineTo(qx + dx * r * 1.3, qy + dy * r * 1.3)
        super().__init__(path)
        self.rig, self.role = rig, role
        self._origin = QPointF(x, y)  # scene feet, +y north
        self._press_scene_pos = QPointF()
        self._press_item_pos = QPointF()
        color = QColor(30, 120, 220) if role == "eye" else QColor(220, 110, 20)
        self.setPen(QPen(color.darker(130), 0.06))
        self.setBrush(QBrush(color if role == "eye" else Qt.NoBrush))
        self.setZValue(6000)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(f"3D camera '{rig.camera.id}': drag to move the " + ("viewer" if role == "eye" else "point it looks at"))

    def scene_point(self) -> QPointF:
        """Current position in scene feet (+y north), mid-drag included."""
        return QPointF(self._origin.x() + self.pos().x(), self._origin.y() - self.pos().y())

    def boundingRect(self):
        return self.path().boundingRect().adjusted(-0.2, -0.2, 0.2, 0.2)

    def shape(self) -> QPainterPath:
        grab = QPainterPath()
        grab.addEllipse(self.path().boundingRect().center(), self.RADIUS * 1.4, self.RADIUS * 1.4)
        return grab

    def mousePressEvent(self, event) -> None:
        self._press_scene_pos = event.scenePos()
        self._press_item_pos = self.pos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self.setPos(self._press_item_pos + (event.scenePos() - self._press_scene_pos))
        self.rig.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()
        if self.pos() != self._press_item_pos:
            self.rig.commit(self.role)


class CameraRig:
    """A 3D camera drawn on the plan: the eye and look-at markers, a dashed
    sight line between them, and a wedge showing the field of view."""

    def __init__(self, gscene: QGraphicsScene, camera, page_height: float,
                 on_moved: Callable[[str, dict], None] | None):
        self.camera, self.page_height, self._on_moved = camera, page_height, on_moved
        self.wedge = QGraphicsPathItem()
        self.wedge.setBrush(QBrush(QColor(30, 120, 220, 40)))
        self.wedge.setPen(QPen(QColor(30, 120, 220, 120), 0.04))
        self.wedge.setZValue(5990)
        self.wedge.setAcceptedMouseButtons(Qt.NoButton)
        self.line = QGraphicsPathItem()
        pen = QPen(QColor(30, 120, 220), 0.05)
        pen.setStyle(Qt.DashLine)
        self.line.setPen(pen)
        self.line.setZValue(5995)
        self.line.setAcceptedMouseButtons(Qt.NoButton)
        self.eye = CameraMarker(self, "eye", camera.x, camera.y)
        self.look = CameraMarker(self, "look", camera.look_x, camera.look_y)
        for item in (self.wedge, self.line, self.eye, self.look):
            gscene.addItem(item)
        self.update()

    def _qt(self, p: QPointF) -> QPointF:
        return QPointF(p.x(), self.page_height - p.y())

    def update(self) -> None:
        eye, look = self.eye.scene_point(), self.look.scene_point()
        line = QPainterPath(self._qt(eye))
        line.lineTo(self._qt(look))
        self.line.setPath(line)
        dx, dy = look.x() - eye.x(), look.y() - eye.y()
        reach = max(math.hypot(dx, dy), 1.0)
        angle = math.atan2(dy, dx)
        half = math.radians(self.camera.fov / 2)
        edge = reach / math.cos(half)  # so the wedge reaches the look-at point along its centre line
        wedge = QPainterPath(self._qt(eye))
        for a in (angle - half, angle + half):
            wedge.lineTo(self._qt(QPointF(eye.x() + edge * math.cos(a), eye.y() + edge * math.sin(a))))
        wedge.closeSubpath()
        self.wedge.setPath(wedge)

    def commit(self, role: str) -> None:
        p = (self.eye if role == "eye" else self.look).scene_point()
        values = {"x": p.x(), "y": p.y()} if role == "eye" else {"look_x": p.x(), "look_y": p.y()}
        if self._on_moved:
            self._on_moved(self.camera.id, {k: round(v, 3) for k, v in values.items()})


def add_camera_items(gscene: QGraphicsScene, doc: SceneDocument,
                     on_moved: Callable[[str, dict], None] | None = None) -> dict[str, CameraRig]:
    return {camera.id: CameraRig(gscene, camera, doc.page_height, on_moved) for camera in doc.cameras}


class View3D(QLabel):
    """Where the 3D view is shown: the rendered picture, scaled to fit, or a
    hint when there's no camera yet. Emits `resized` so the window can
    re-render at the new size once resizing settles."""

    resized = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 150)
        self.setWordWrap(True)
        self.setStyleSheet("background: #EEF4F8; color: #3A3833;")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()


class CameraPanel(QGroupBox):
    """The right column's 3D camera section (M11): which camera the 3D view
    uses, add/delete, and its values typed in. Separate from the properties
    panel, which is disabled whenever no object is selected."""

    FIELDS = (("x", "X"), ("y", "Y"), ("z", "Eye height"), ("look_x", "Look at X"),
              ("look_y", "Look at Y"), ("look_z", "Look at height"), ("fov", "Field of view"))

    def __init__(self, parent: QWidget | None = None):
        super().__init__("3D camera", parent)
        self.camera_combo = QComboBox()
        self.add_button = QPushButton("Add")
        self.delete_button = QPushButton("Delete")
        chooser = QHBoxLayout()
        chooser.addWidget(self.camera_combo, 1)
        chooser.addWidget(self.add_button)
        chooser.addWidget(self.delete_button)
        layout = QFormLayout(self)
        layout.addRow(chooser)
        self.spins: dict[str, QDoubleSpinBox] = {}
        for key, label in self.FIELDS:
            spin = QDoubleSpinBox()
            spin.setRange(10, 150) if key == "fov" else spin.setRange(-1000, 1000)
            spin.setDecimals(2)
            spin.setKeyboardTracking(False)  # commit on Enter / focus out, not per keystroke
            spin.setSuffix("°" if key == "fov" else " ft")
            layout.addRow(label, spin)
            self.spins[key] = spin
        self.x_spin, self.y_spin, self.z_spin = self.spins["x"], self.spins["y"], self.spins["z"]
        self.fov_spin = self.spins["fov"]
        self.aim_label = QLabel("—")
        self.aim_label.setToolTip("Heading (clockwise from plan-north) and tilt, from the look-at point")
        layout.addRow("Aim", self.aim_label)

    def show_cameras(self, cameras, active_id: str | None) -> None:
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        for camera in cameras:
            self.camera_combo.addItem(camera.id)
        if active_id is not None:
            self.camera_combo.setCurrentText(active_id)
        self.camera_combo.blockSignals(False)
        active = next((c for c in cameras if c.id == active_id), None)
        for key, spin in self.spins.items():
            spin.blockSignals(True)
            spin.setValue(getattr(active, key) if active else 0.0)
            spin.setEnabled(active is not None)
            spin.blockSignals(False)
        self.delete_button.setEnabled(active is not None)
        self.aim_label.setText(f"heading {active.heading:.0f}°, tilt {active.tilt:.0f}°" if active else "—")

    def fields_enabled(self) -> bool:
        return self.x_spin.isEnabled()


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
    `SceneDocument`) to make objects selectable/movable (annotations and
    keepouts included, clickable along their dashed outline only) —
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
            scene_object = doc.get(obj.id) if doc is not None else None
            _add_annotation_item(
                gscene, obj, label, page_height, line_width, scene_object, on_object_moved, on_drag_start, on_drag_end
            )
            continue
        material = materials.resolve(obj.material)
        scene_object = doc.get(obj.id) if doc is not None else None
        _add_material_item(
            gscene, obj, material, page_height, line_width, scene_object, on_object_moved, on_drag_start, on_drag_end,
            units=doc.units if doc is not None else "ft",
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

    Zoom always anchors on the current center of the viewport — "the
    center of the image," both zooming in and out — via Qt's built-in
    `AnchorViewCenter`. Simplified on request 2026-09-23, replacing an
    earlier version that anchored on the *selected object's* center
    instead (falling back to the viewport center only when nothing was
    selected), with the anchor point manually corrected afterwards by
    hand via the scrollbars. That approach had two real problems, one
    of them Rich's own bug report ("zoom out seems to scale wildly and
    then recenter"): the anchor point would silently jump between the
    viewport center and an object's center the moment something got
    selected or deselected mid-session, with no visual continuity
    between the two; and the manual scrollbar correction turned out to
    mostly be a no-op in practice, since `QGraphicsView`'s *implicit*
    scene rect (used whenever `setSceneRect()` was never called
    explicitly, which this app never does) auto-expands to always
    include the current viewport — so the scrollbar range was `(0, 0)`
    almost all the time, before or after zooming, leaving nothing for
    that correction to actually adjust. `AnchorViewCenter` is Qt's own
    built-in, well-tested handling of exactly this "zoom about the
    view's center" case, including that same edge case, so it replaces
    the hand-rolled version outright rather than patching it. Per-object
    zoom-following (matching the *rotation axis* the resize/rotate
    handles use) is a "fancier zoom" left for later, on request."""

    ZOOM_PER_TICK = 1.05  # was 1.15; that felt too aggressive per scroll tick

    zoomed = Signal()  # after every wheel zoom step

    def __init__(self, scene: QGraphicsScene | None = None):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        # Track the pointer even with no button held, so Tab knows what's
        # under it now, not just where the last click was.
        self.setMouseTracking(True)
        self._pointer_pos = None  # viewport pixels, not scene coords — survives zoom/pan
        self._full_quality = True
        self._zoom_settle_timer = QTimer(self)
        self._zoom_settle_timer.setSingleShot(True)
        self._zoom_settle_timer.setInterval(self.ZOOM_SETTLE_MS)
        self._zoom_settle_timer.timeout.connect(lambda: self._set_interactive_quality(True))
        # Covers the viewport area outside the scene's own background
        # (e.g. once panned/zoomed past the drawing's edge) with the same
        # off-white paper tone, so there's no stark-white gap at the edges.
        self.setBackgroundBrush(QBrush(BACKGROUND_COLOR))

    ZOOM_SETTLE_MS = 200  # full-quality redraw this long after the last scroll

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom in proportion to how far the wheel or trackpad actually
        scrolled: a mouse notch (120) is one `ZOOM_PER_TICK` step, a
        trackpad's many small deltas are fractions of one. Two real bugs
        this replaces: every event zoomed a full step whatever its size
        (a trackpad flick was dozens of them, each forcing a full redraw,
        so zoom lagged behind the fingers), and a zero-length event — how a
        trackpad gesture ends — counted as 'zoom out', so every zoom backed
        up one step at the end."""
        delta = event.angleDelta().y()
        event.accept()
        if delta == 0:
            return
        factor = self.ZOOM_PER_TICK ** (delta / 120.0)
        self._set_interactive_quality(False)
        self.scale(factor, factor)
        self._zoom_settle_timer.start()
        self.zoomed.emit()

    def _set_interactive_quality(self, full: bool) -> None:
        """While a zoom gesture is under way, redraw lighter: no edge
        smoothing and no paver joint lines (thousands of brick outlines,
        about half the cost of a redraw). Full quality returns
        `ZOOM_SETTLE_MS` after the last scroll."""
        if full == self._full_quality:
            return
        self._full_quality = full
        self.setRenderHint(QPainter.Antialiasing, full)
        if self.scene() is not None:
            for item in self.scene().items():
                joints = getattr(item, "joints_item", None)
                if joints is not None:
                    joints.setVisible(full)

    def mousePressEvent(self, event) -> None:
        self._pointer_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._pointer_pos = event.position().toPoint()
        super().mouseMoveEvent(event)

    def focusNextPrevChild(self, next: bool) -> bool:
        """Qt calls this for Tab/Shift+Tab while the canvas has focus. With
        an object selected, Tab instead steps the selection through every
        object under the mouse pointer, top to bottom, wrapping around
        (Shift+Tab goes bottom to top) — Rich's way to reach an object
        buried under others. Tab is kept on the canvas even when nothing
        is under the pointer, so it never jumps focus away unexpectedly.
        With nothing selected, Tab moves focus as usual; in the properties
        panel it's untouched, since this only runs while the canvas has
        focus."""
        scene = self.scene()
        if scene is None or not scene.selectedItems():
            return super().focusNextPrevChild(next)
        self._cycle_selection_under_pointer(scene, forward=next)
        return True

    def _cycle_selection_under_pointer(self, scene: QGraphicsScene, forward: bool) -> None:
        if self._pointer_pos is None:
            return
        point = self.mapToScene(self._pointer_pos)
        stack = [i for i in scene.items(point) if isinstance(i, EditableItem) and i.isVisible()]  # topmost first
        if not stack:
            return
        current = scene.selectedItems()[0]
        if current in stack:
            target = stack[(stack.index(current) + (1 if forward else -1)) % len(stack)]
        else:
            target = stack[0] if forward else stack[-1]
        scene.clearSelection()
        target.setSelected(True)

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
        self._materials = materials
        self.id_label = QLabel("—")
        # Size: editable width x height (or one diameter) for shapes that can
        # be reshaped directly; a read-only readout for anything else.
        self.size_width = self._size_spin()
        self.size_times = QLabel("×")
        self.size_height = self._size_spin()
        self.size_label = QLabel("—")
        self.size_label.setToolTip("Actual size after scaling (updates live while resizing)")
        # Height (3D view): how tall the object stands, and how high its
        # bottom sits — its own value or the one it inherits
        self.solid_height = self._size_spin(minimum=0.0)
        self.solid_height.setToolTip("How tall the object stands in the 3D view")
        self.solid_base = self._size_spin(minimum=0.0)
        self.solid_base.setPrefix("from ")
        self.solid_base.setToolTip("How high above the ground its bottom sits (e.g. a tub on its pad)")
        height_row = QWidget()
        height_layout = QHBoxLayout(height_row)
        height_layout.setContentsMargins(0, 0, 0, 0)
        height_layout.addWidget(self.solid_height)
        height_layout.addWidget(self.solid_base)
        self._height_row = height_row
        size_row = QWidget()
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.size_width, self.size_times, self.size_height, self.size_label):
            size_layout.addWidget(widget)
        self._size_row = size_row
        self._show_size_widgets(editable=False, diameter=False)
        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setRange(-3600, 3600)
        self.rotation_spin.setSuffix("°")
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 100)
        self.scale_spin.setSingleStep(0.05)
        self.material_combo = QComboBox()
        for material_id, material in sorted(materials.materials.items(), key=lambda kv: kv[1].name):
            self.material_combo.addItem(_swatch_icon(material), material.name, userData=material_id)
        from .pavers import PATTERN_LABELS

        self.pattern_label = QLabel("Pattern")
        self.pattern_combo = QComboBox()
        for key, label in PATTERN_LABELS.items():
            self.pattern_combo.addItem(label, key)

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
        layout.addRow("Size", self._size_row)
        layout.addRow("Height", self._height_row)
        layout.addRow("Rotation", self.rotation_spin)
        layout.addRow("Scale", self.scale_spin)
        layout.addRow("Material", self.material_combo)
        layout.addRow(self.pattern_label, self.pattern_combo)
        layout.addRow("Relation", self.relation_type_combo)
        layout.addRow("Target", self.relation_target_combo)
        layout.addRow(self.relation_param1_label, self.relation_param1_spin)
        layout.addRow(self.relation_param2_label, self.relation_param2_spin)
        layout.addRow(buttons)
        self.setEnabled(False)
        self._lock_minimum_width()
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
        widgets = (*widgets, self.pattern_combo)
        for widget in widgets:
            widget.blockSignals(True)

        from .pavers import paver_spec

        spec = paver_spec(self._materials.resolve(obj.material), obj.pattern, "ft")
        self.pattern_label.setVisible(spec is not None)
        self.pattern_combo.setVisible(spec is not None)
        if spec is not None:
            self.pattern_combo.setCurrentIndex(self.pattern_combo.findData(spec.pattern))

        self.rotation_spin.setValue(obj.transform.rotation)
        self.scale_spin.setValue(obj.transform.scale)
        self.material_combo.setCurrentIndex(self.material_combo.findData(obj.material or ""))
        # Annotations and keepouts carry no material; there's nothing to pick.
        self.material_combo.setEnabled(obj.material is not None)

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

    def _lock_minimum_width(self) -> None:
        """Fix the panel's minimum width at its widest content — every row
        that can appear (size boxes, pattern, relation fields) shown at
        once. Otherwise showing one widens the panel, squeezes the canvas
        beside it, and (zoom anchors on the view centre) slides the drawing
        sideways every time the selection changes — a real bug."""
        toggled = (
            self.size_width, self.size_times, self.size_height, self.pattern_label, self.pattern_combo,
            self.relation_target_combo, self.relation_param1_label, self.relation_param1_spin,
            self.relation_param2_label, self.relation_param2_spin,
        )
        was_hidden = [w for w in toggled if w.isHidden()]
        for widget in was_hidden:
            widget.setVisible(True)
        self.layout().activate()
        self.setMinimumWidth(self.minimumSizeHint().width())
        for widget in was_hidden:
            widget.setVisible(False)

    @staticmethod
    def _size_spin(minimum: float = 0.01) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, 10000)
        spin.setDecimals(2)
        spin.setSingleStep(0.25)
        # commit on Enter / leaving the box / an arrow click, not per
        # keystroke — typing "12" must not reshape the object to 1 ft first
        spin.setKeyboardTracking(False)
        spin.setToolTip("Type a new size to reshape the object in this direction (keeps its centre)")
        return spin

    def _show_size_widgets(self, editable: bool, diameter: bool) -> None:
        self.size_width.setVisible(editable)
        self.size_times.setVisible(editable and not diameter)
        self.size_height.setVisible(editable and not diameter)
        self.size_label.setVisible(not editable)

    def show_size(self, dims, units: str, fallback_text: str) -> None:
        """`dims` from `dimensions.object_dimensions` (already scaled), or
        None to show `fallback_text` read-only."""
        if dims is None:
            self._show_size_widgets(editable=False, diameter=False)
            self.size_label.setText(fallback_text)
            return
        self._show_size_widgets(editable=True, diameter=dims.diameter_only)
        for spin, value in ((self.size_width, dims.width), (self.size_height, dims.height)):
            spin.blockSignals(True)
            spin.setSuffix(f" {units}")
            spin.setEnabled(value is not None)
            spin.setValue(value or 0.0)
            spin.blockSignals(False)
        self.size_width.setPrefix("⌀ " if dims.diameter_only else "")

    def show_solid(self, solid, units: str) -> None:
        for spin, value in ((self.solid_height, solid.height), (self.solid_base, solid.base)):
            spin.blockSignals(True)
            spin.setSuffix(f" {units}")
            spin.setValue(value)
            spin.blockSignals(False)

    def size_text(self) -> str:
        """What the Size row currently says, as text (for tests and tooltips)."""
        if self.size_label.isVisibleTo(self):
            return self.size_label.text()
        units = self.size_width.suffix().strip()
        w, h = self.size_width.value(), self.size_height.value()
        if self.size_height.isVisibleTo(self):
            return f"{w:.2f} × {h:.2f} {units}"
        return f"⌀ {w:.2f} {units}"

    def clear(self) -> None:
        self.id_label.setText("—")
        self._show_size_widgets(editable=False, diameter=False)
        self.size_label.setText("—")
        self.setEnabled(False)




class ExportOptionsDialog(QDialog):
    """File > Export's second step, after the file picker: the export
    options the CLI has, for the designer — style (flat design colors or the
    watercolor art mode) and its wash, DPI (for PNGs, and for art in any
    format, where it's the painting's resolution), legend, annotations,
    scale bar, north arrow and its angle. `options()` returns exactly the
    keyword arguments `EditorSession.export()` takes for this file."""

    DEFAULTS = {
        "mode": "flat",
        "wash": "diffuse",
        "dpi": 300,
        "show_legend": True,  # what export always did before this dialog existed
        "scale_indicator": True,
        "scale_bar": False,
        "north_arrow": False,
        "north_deg": 0.0,
    }

    SIZES_3D = ((1600, 1000), (2400, 1500), (3200, 2000))

    def __init__(self, parent: QWidget | None, path: str | Path, show_annotations: bool, previous: dict | None = None,
                 cameras: list[str] | None = None, active_camera: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export options")
        self._path = Path(path)
        values = {**self.DEFAULTS, "show_annotations": show_annotations, **(previous or {})}

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Design (flat colors)", "flat")
        self.mode_combo.addItem("Art (watercolor and pencil)", "art")
        self.mode_combo.addItem("3D view (from a camera)", "3d")
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(values["mode"]))
        self.wash_combo = QComboBox()
        self.wash_combo.addItem("Diffuse (soft, pooled edges)", "diffuse")
        self.wash_combo.addItem("Layered (crisp glazes)", "layered")
        self.wash_combo.setCurrentIndex(self.wash_combo.findData(values["wash"]))
        self.camera_combo = QComboBox()
        self.camera_combo.addItems(cameras or [])
        if active_camera:
            self.camera_combo.setCurrentText(active_camera)
        self.size_combo = QComboBox()
        for w, h in self.SIZES_3D:
            self.size_combo.addItem(f"{w} × {h} px", (w, h))
        remembered_size = tuple(values.get("size", self.SIZES_3D[0]))
        self.size_combo.setCurrentIndex(max(0, self.size_combo.findData(remembered_size)))

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(36, 1200)
        self.dpi_spin.setSuffix(" DPI")
        self.dpi_spin.setValue(int(values["dpi"]))
        self.dpi_spin.setToolTip(
            "Pixels per inch of the drawing's print size. Flat SVG/PDF are vector and don't use it; "
            "art mode is a painting, so it applies to every format (higher is slower)"
        )
        self.legend_check = QCheckBox("Legend box")
        self.legend_check.setChecked(values["show_legend"])
        self.scale_indicator_check = QCheckBox("Scale indicator on the drawing")
        self.scale_indicator_check.setChecked(values["scale_indicator"])
        self.annotations_check = QCheckBox("Annotations (dashed technical marks)")
        self.annotations_check.setChecked(values["show_annotations"])
        self.scale_bar_check = QCheckBox("Scale bar")
        self.scale_bar_check.setChecked(values["scale_bar"])
        self.north_arrow_check = QCheckBox("North arrow")
        self.north_arrow_check.setChecked(values["north_arrow"])
        self.north_angle_spin = QDoubleSpinBox()
        self.north_angle_spin.setRange(-360, 360)
        self.north_angle_spin.setSuffix("°")
        self.north_angle_spin.setValue(values["north_deg"])
        self.north_angle_spin.setToolTip("Degrees clockwise from page-up that north lies at")
        self.north_arrow_check.toggled.connect(self.north_angle_spin.setEnabled)
        self.north_angle_spin.setEnabled(self.north_arrow_check.isChecked())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.mode_combo.currentIndexChanged.connect(self._update_enabled)
        self._update_enabled()

        layout = QFormLayout(self)
        layout.addRow("Style", self.mode_combo)
        layout.addRow("Wash", self.wash_combo)
        layout.addRow("Camera", self.camera_combo)
        layout.addRow("Picture size", self.size_combo)
        layout.addRow("Resolution", self.dpi_spin)
        layout.addRow(self.legend_check)
        layout.addRow(self.scale_indicator_check)
        layout.addRow(self.annotations_check)
        layout.addRow(self.scale_bar_check)
        layout.addRow(self.north_arrow_check)
        layout.addRow("North is at", self.north_angle_spin)
        layout.addRow(buttons)

    def _update_enabled(self) -> None:
        from .render import takes_dpi

        mode = self.mode_combo.currentData()
        self.dpi_spin.setEnabled(takes_dpi(self._path, mode))
        self.wash_combo.setEnabled(mode == "art")
        is_3d = mode == "3d"
        self.camera_combo.setEnabled(is_3d and self.camera_combo.count() > 0)
        self.size_combo.setEnabled(is_3d)
        for check in (self.legend_check, self.scale_indicator_check, self.annotations_check,
                      self.scale_bar_check, self.north_arrow_check):
            check.setEnabled(not is_3d)  # plan-only; a 3D picture has no legend or scale

    def remembered(self) -> dict:
        """Every choice, for pre-filling the next export (DPI and wash
        included even when this export doesn't use them)."""
        return {
            "mode": self.mode_combo.currentData(),
            "wash": self.wash_combo.currentData(),
            "dpi": self.dpi_spin.value(),
            "show_legend": self.legend_check.isChecked(),
            "scale_indicator": self.scale_indicator_check.isChecked(),
            "show_annotations": self.annotations_check.isChecked(),
            "scale_bar": self.scale_bar_check.isChecked(),
            "north_arrow": self.north_arrow_check.isChecked(),
            "north_deg": self.north_angle_spin.value(),
            "size": self.size_combo.currentData(),
        }

    def options(self) -> dict:
        from .render import takes_dpi
        from .render_art import ArtStyle

        options = self.remembered()
        if options["mode"] == "3d":
            width, height = options["size"]
            return {"mode": "3d", "camera": self.camera_combo.currentText() or None, "width": width, "height": height}
        options.pop("size")
        wash = options.pop("wash")
        if not takes_dpi(self._path, options["mode"]):
            del options["dpi"]  # flat SVG/PDF are vector
        if options["mode"] == "art":
            options["style"] = ArtStyle(wash=wash)
        return options


ART_PREVIEW_MIN_DPI = 30.0
ART_PREVIEW_MAX_DPI = 200.0
_ART_PREVIEW_CACHE_SIZE = 6


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
        # "[*]" is Qt's placeholder: it shows as "*" only while
        # setWindowModified(True) — see _update_save_state.
        self.setWindowTitle("Landscape Editor[*]")

        self.session = EditorSession(materials_path, rules_path)
        self._show_annotations = False
        self._selected_id: str | None = None
        self._hidden_layers: set[str] = set()
        self._selection_handles: list[SelectionHandle] = []
        self._last_known_mtime_ns: int | None = None
        self._file_watcher = QFileSystemWatcher()
        self._file_watcher.fileChanged.connect(self._on_file_changed_externally)
        self._layers_menu = None
        self._last_export_options: dict | None = None  # pre-fills the next File > Export
        # Design / Art preview (M6). The preview is a read-only painting of
        # the scene laid over the page; see _show_art_preview.
        self._art_mode = False
        self._3d_mode = False
        self._3d_cache: dict[tuple, "QPixmap"] = {}  # (revision, camera, size, layers) -> picture
        self._3d_resize_timer = QTimer(self)
        self._3d_resize_timer.setSingleShot(True)
        self._3d_resize_timer.setInterval(150)  # re-render once resizing settles
        self._3d_resize_timer.timeout.connect(self._show_3d_view)
        self._art_cache: dict[tuple, tuple[float, "QPixmap"]] = {}  # key -> (dpi, pixmap), oldest first
        self._art_rendered_dpi = 0.0
        self._art_zoom_timer = QTimer(self)
        self._art_zoom_timer.setSingleShot(True)
        self._art_zoom_timer.setInterval(250)  # re-render once the wheel settles, not on every tick
        self._art_zoom_timer.timeout.connect(self._on_art_zoom_settled)

        self._view = SceneGraphicsView()
        self._view.zoomed.connect(self._on_view_zoomed)
        self._panel = PropertiesPanel(self.session.materials)
        self._panel.rotation_spin.valueChanged.connect(self._on_rotation_changed)
        self._panel.scale_spin.valueChanged.connect(self._on_scale_changed)
        self._panel.material_combo.currentIndexChanged.connect(self._on_material_changed)
        self._panel.pattern_combo.currentIndexChanged.connect(self._on_pattern_changed)
        self._panel.size_width.valueChanged.connect(lambda v: self._on_size_edited("width", v))
        self._panel.size_height.valueChanged.connect(lambda v: self._on_size_edited("height", v))
        self._panel.solid_height.valueChanged.connect(lambda v: self._on_solid_edited("height", v))
        self._panel.solid_base.valueChanged.connect(lambda v: self._on_solid_edited("base", v))
        self._panel.apply_relation_button.clicked.connect(self._on_apply_relation)
        self._panel.clear_relation_button.clicked.connect(self._on_clear_relation)

        self._camera_panel = CameraPanel()
        self._camera_panel.add_button.clicked.connect(self._on_add_camera)
        self._camera_panel.delete_button.clicked.connect(self._on_delete_camera)
        self._camera_panel.camera_combo.currentTextChanged.connect(self._on_camera_chosen)
        for key, spin in self._camera_panel.spins.items():
            spin.valueChanged.connect(lambda v, key=key: self._on_camera_field(key, v))
        self._active_camera_id: str | None = None
        self._camera_rigs: dict = {}
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._panel)
        right_layout.addWidget(self._camera_panel)
        right_layout.addStretch(1)

        self._view3d = View3D()
        self._view3d.resized.connect(lambda: self._3d_mode and self._3d_resize_timer.start())
        self._left_stack = QStackedWidget()
        self._left_stack.addWidget(self._view)
        self._left_stack.addWidget(self._view3d)

        splitter = QSplitter()
        splitter.addWidget(self._left_stack)
        splitter.addWidget(right)
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
        self.session.on_state_change = self._update_save_state
        self._update_save_state()

    def _build_menu(self) -> None:
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QFileDialog

        file_menu = self.menuBar().addMenu("&File")

        # One action shared by the menu, Ctrl+S and the toolbar button, so
        # all three enable/disable together (see _update_save_state).
        self._save_action = file_menu.addAction("&Save")
        self._save_action.setShortcut(QKeySequence.Save)
        self._save_action.setToolTip("Save to the scene's YAML file (Ctrl+S)")
        self._save_action.triggered.connect(lambda: self._save_or_warn())

        save_as_action = file_menu.addAction("Save &As…")

        def _save_as() -> None:
            path, _ = QFileDialog.getSaveFileName(self, "Save Scene As", "", "Scene YAML (*.yaml)")
            if path:
                self._save_or_warn(path)

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

        from PySide6.QtGui import QActionGroup

        view_menu = self.menuBar().addMenu("&View")
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        self._design_action = view_menu.addAction("&Design")
        self._design_action.setShortcut(QKeySequence("Ctrl+1"))
        self._design_action.setToolTip("Edit the plan: flat colors, selectable shapes (Ctrl+1)")
        self._art_action = view_menu.addAction("&Art preview")
        self._art_action.setShortcut(QKeySequence("Ctrl+2"))
        self._art_action.setToolTip("Preview the watercolor-and-pencil art render; read-only (Ctrl+2)")
        self._view3d_action = view_menu.addAction("&3D view")
        self._view3d_action.setShortcut(QKeySequence("Ctrl+3"))
        self._view3d_action.setToolTip("See the plan in 3D from the chosen camera; read-only (Ctrl+3)")
        for action in (self._design_action, self._art_action, self._view3d_action):
            action.setCheckable(True)
            mode_group.addAction(action)
        self._design_action.setChecked(True)
        self._design_action.triggered.connect(lambda: self._set_view_mode("design"))
        self._art_action.triggered.connect(lambda: self._set_view_mode("art"))
        self._view3d_action.triggered.connect(lambda: self._set_view_mode("3d"))

        toolbar = self.addToolBar("File")
        toolbar.setMovable(False)
        toolbar.addAction(self._save_action)
        self._unsaved_label = QLabel("● Unsaved changes")
        self._unsaved_label.setStyleSheet(f"color: {_VIOLATION_COLOR.name()}; padding-left: 8px;")
        # A widget in a toolbar is shown/hidden through the QAction that
        # addWidget() returns, not the widget's own setVisible().
        self._unsaved_label_action = toolbar.addWidget(self._unsaved_label)
        toolbar.addSeparator()
        toolbar.addAction(self._design_action)
        toolbar.addAction(self._art_action)
        toolbar.addAction(self._view3d_action)

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
        if Path(path).suffix.lower() not in EXPORT_EXTENSIONS:
            QMessageBox.warning(
                self, "Export failed", f"Unsupported file type '{Path(path).suffix}' (use .png, .svg, or .pdf)"
            )
            return
        dialog = ExportOptionsDialog(
            self, path, self._show_annotations, self._last_export_options,
            cameras=[c.id for c in self.session.doc.cameras], active_camera=self._active_camera_id,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._last_export_options = dialog.remembered()
        try:
            self.session.export(path, **dialog.options())
        except (ValueError, OSError) as exc:
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
        self._watch_scene_file()
        self._update_save_state()

    def save_scene(self, path: str | Path | None = None) -> None:
        self.session.save(path)
        if path is not None:
            self._watch_scene_file()  # Save As: the new file is the one being edited now
        else:
            self._remember_own_write()

    def _save_or_warn(self, path: str | Path | None = None) -> bool:
        """`save_scene` for the GUI's own Save/Save As/close-prompt paths:
        a failed write (permissions, a vanished folder) becomes a warning
        dialog, not an unhandled exception, and leaves the document
        marked unsaved. Returns whether the save succeeded."""
        try:
            self.save_scene(path)
        except OSError as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Save failed", f"Couldn't save the scene:\n\n{exc}")
            return False
        return True

    def _update_save_state(self) -> None:
        """Keep every "unsaved changes" cue in step with `session.dirty`:
        the toolbar label, the "*" in the window title, and the Save
        button/menu item/Ctrl+S (enabled only when there's something to
        save). Wired to `EditorSession.on_state_change`, which fires for
        every edit — including a plain drag, which never rebuilds the
        scene, so this can't just hang off `_rebuild_scene`."""
        dirty = self.session.dirty
        self._save_action.setEnabled(dirty)
        self._unsaved_label_action.setVisible(dirty)
        if self.session.scene_path is not None:
            self.setWindowTitle(f"Landscape Editor — {self.session.scene_path.name}[*]")
        self.setWindowModified(dirty)

    def closeEvent(self, event) -> None:
        """Closing with unsaved changes asks Save / Discard / Cancel. On
        Discard, the `.autosave` sidecar is left in place as a backup."""
        if self.session.dirty:
            from PySide6.QtWidgets import QMessageBox

            name = self.session.scene_path.name if self.session.scene_path else "the scene"
            choice = QMessageBox.question(
                self,
                "Unsaved changes",
                f"Save changes to '{name}' before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if choice == QMessageBox.Cancel or (choice == QMessageBox.Save and not self._save_or_warn()):
                event.ignore()
                return
        super().closeEvent(event)

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
            on_drag_end=self._on_object_drag_end,
            line_width=_line_width_for_zoom(zoom),
        )
        if self.session.rules:
            add_violation_overlays(gscene, self.session.violations, doc.page_height)
        # kept by name: QGraphicsScene.items() leaves out hidden items, so
        # during the art preview they can't be found that way
        cameras = self.session.doc.cameras
        if self._active_camera_id not in {c.id for c in cameras}:
            self._active_camera_id = cameras[0].id if cameras else None
        self._camera_rigs = add_camera_items(gscene, doc, on_moved=self._on_camera_dragged)
        self._camera_panel.show_cameras(cameras, self._active_camera_id)
        self._overlay_items = add_overlay_items(
            gscene, doc, self.session.resolved, self.session.materials, _line_width_for_zoom(zoom),
            hidden_layers=self._hidden_layers, on_moved=self.session.set_overlay_position,
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
        if self._art_mode:
            self._show_art_preview()  # a rebuild (undo, layer toggle, ...) re-paints the preview
        elif previously_selected:
            self._select_item_by_id(previously_selected)
        self._update_status_bar()
        if self._art_mode:  # after the rule-violation summary, which would otherwise replace it
            self.statusBar().showMessage("Art preview — read-only. Switch to Design (Ctrl+1) to edit.")
        if self._3d_mode:
            self._show_3d_view()
        self._undo_action.setEnabled(self.session.can_undo)
        self._redo_action.setEnabled(self.session.can_redo)

    # --- 3D cameras (M11) -------------------------------------------------------

    def _on_add_camera(self) -> None:
        self._active_camera_id = self.session.add_camera()
        self._rebuild_scene()

    def _on_delete_camera(self) -> None:
        if self._active_camera_id:
            self.session.delete_camera(self._active_camera_id)
            self._active_camera_id = None
            self._rebuild_scene()

    def _on_camera_chosen(self, camera_id: str) -> None:
        if camera_id and camera_id != self._active_camera_id:
            self._active_camera_id = camera_id
            self._rebuild_scene()

    def _on_camera_field(self, key: str, value: float) -> None:
        if not self._active_camera_id:
            return
        try:
            self.session.set_camera(self._active_camera_id, **{key: value})
        except ValueError as exc:
            self.statusBar().showMessage(f"Can't set camera: {exc}")
        self._rebuild_scene()

    def _on_camera_dragged(self, camera_id: str, values: dict) -> None:
        """A camera marker was dropped: commit, then redraw once the mouse
        event has returned (the marker is still handling it)."""
        self._active_camera_id = camera_id
        try:
            self.session.set_camera(camera_id, **values)
        except ValueError as exc:
            self.statusBar().showMessage(f"Can't move camera: {exc}")
        QTimer.singleShot(0, self._rebuild_scene)

    def _on_object_drag_end(self) -> None:
        """A move-drag has finished. The drag itself only updated the
        document and the item's own outline, so bring everything else up to
        date: recompute the resolved geometry and the rule check (a real
        bug when this was missing — the art preview, and any later redraw,
        still used the pre-drag geometry, so a moved firepit snapped back
        to its old spot on switching views, though the file had saved
        correctly), autosave, then redraw. The redraw is queued until the
        mouse event has fully returned: replacing the scene inside it would
        destroy the item still handling that event."""
        self.session.recompute()
        self.session.autosave()
        QTimer.singleShot(0, self._rebuild_scene)

    # --- Design / Art preview ---------------------------------------------

    def _set_art_mode(self, on: bool) -> None:
        self._set_view_mode("art" if on else "design")

    def _set_view_mode(self, mode: str) -> None:
        """Design, Art preview (painted over the plan canvas) or 3D view (a
        picture in place of the canvas)."""
        art, three = mode == "art", mode == "3d"
        if (art, three) == (self._art_mode, self._3d_mode):
            return
        self._art_mode, self._3d_mode = art, three
        self._left_stack.setCurrentWidget(self._view3d if three else self._view)
        self._rebuild_scene()  # rebuilds the design items, then paints the art preview or the 3D view

    # --- 3D view (M11) --------------------------------------------------------

    def _show_3d_view(self) -> None:
        """Render the active camera's view at the widget's size (in device
        pixels, so it's sharp on a Retina screen), from a small cache keyed
        by the document's revision, the camera, the size and hidden layers."""
        if not self._3d_mode:
            return
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtWidgets import QApplication

        from . import render3d
        from .geometry import ResolvedScene

        camera = next((c for c in self.session.doc.cameras if c.id == self._active_camera_id), None)
        if camera is None:
            self._view3d.setPixmap(QPixmap())
            self._view3d.setText(
                "No camera yet.\n\nClick Add in the 3D camera section to place one on the plan — "
                "then drag its blue eye marker to where you'd stand and its orange crosshair to what you'd look at."
            )
            self.statusBar().showMessage("3D view — add a camera to see the plan in 3D.")
            return
        dpr = self._view3d.devicePixelRatioF()
        width = max(64, round(self._view3d.width() * dpr))
        height = max(48, round(self._view3d.height() * dpr))
        from dataclasses import astuple

        key = (self.session.revision, astuple(camera), width, height, frozenset(self._hidden_layers))
        pixmap = self._3d_cache.get(key)
        if pixmap is None:
            scene = ResolvedScene(objects=[o for o in self.session.resolved.objects if o.layer not in self._hidden_layers])
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                image = render3d.render_3d_image(self.session.doc, scene, self.session.materials, camera,
                                                 width=width, height=height)
            finally:
                QApplication.restoreOverrideCursor()
            data = image.tobytes()
            qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(qimage)
            pixmap.setDevicePixelRatio(dpr)
            self._3d_cache[key] = pixmap
            while len(self._3d_cache) > 6:
                self._3d_cache.pop(next(iter(self._3d_cache)))
        self._view3d.setText("")
        self._view3d.setPixmap(pixmap)
        self.statusBar().showMessage(
            f"3D view — from camera '{camera.id}'. Adjust it in the 3D camera section; Ctrl+1 to edit the plan."
        )

    def _art_preview_dpi(self) -> float:
        """About one rendered pixel per screen pixel at the current zoom —
        sharp without paying for print resolution — clamped."""
        doc = self.session.doc
        px_per_ft = self._view.transform().m11() * self._view.devicePixelRatioF()
        return min(max(px_per_ft * 72.0 / doc.scale, ART_PREVIEW_MIN_DPI), ART_PREVIEW_MAX_DPI)

    def _art_pixmap(self, dpi: float):
        """The painting for the current document, layers and annotations,
        from a small cache keyed by `session.revision` — so toggling back
        and forth, or undoing to an already-painted state, costs nothing.
        A cached render is reused if it's at least as sharp as asked for."""
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtWidgets import QApplication

        from . import render_art
        from .geometry import ResolvedScene

        key = (self.session.revision, frozenset(self._hidden_layers), self._show_annotations)
        cached = self._art_cache.get(key)
        if cached and cached[0] >= dpi * 0.95:
            return cached

        scene = ResolvedScene(objects=[o for o in self.session.resolved.objects if o.layer not in self._hidden_layers])
        self.statusBar().showMessage("Rendering art preview…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            image = render_art.render_art_image(
                self.session.doc, scene, self.session.materials, dpi=dpi, show_annotations=self._show_annotations,
                show_legend=True, scale_indicator=True,  # the drawing's overlays, as on the design canvas
            )
        finally:
            QApplication.restoreOverrideCursor()
        data = image.tobytes()
        qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format_RGB888).copy()
        entry = (dpi, QPixmap.fromImage(qimage))
        self._art_cache.pop(key, None)
        self._art_cache[key] = entry
        while len(self._art_cache) > _ART_PREVIEW_CACHE_SIZE:
            self._art_cache.pop(next(iter(self._art_cache)))
        return entry

    def _show_art_preview(self) -> None:
        """Hide every design item and lay the painting over the page. The
        preview is read-only: nothing under it is visible or clickable, and
        any selection is cleared (which also removes the handles)."""
        scene = self._view.scene()
        scene.clearSelection()
        for item in scene.items():
            if item.parentItem() is None:
                item.setVisible(False)
        dpi, pixmap = self._art_pixmap(self._art_preview_dpi())
        self._art_rendered_dpi = dpi
        doc = self.session.doc
        preview = QGraphicsPixmapItem(pixmap)
        preview.setTransformationMode(Qt.SmoothTransformation)
        preview.setScale(doc.page_width / pixmap.width())  # pixels -> scene feet
        preview.setZValue(10_000)
        preview.setAcceptedMouseButtons(Qt.NoButton)
        scene.addItem(preview)

    def _on_view_zoomed(self) -> None:
        if self._art_mode:
            self._art_zoom_timer.start()

    def _on_art_zoom_settled(self) -> None:
        """Re-paint when zooming in has made the current render visibly soft;
        zooming out never needs it (the existing render is sharper still)."""
        if self._art_mode and self._art_preview_dpi() > self._art_rendered_dpi * 1.3:
            self._rebuild_scene()

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
            self._show_selected_size()
            self._show_selected_solid()
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

        resize_handle = SelectionHandle(
            "resize", target, self._view, self._on_handle_resized, on_preview=self._show_selected_size
        )
        rotate_handle = SelectionHandle("rotate", target, self._view, self._on_handle_rotated)
        scene = self._view.scene()
        scene.addItem(resize_handle)
        scene.addItem(rotate_handle)
        self._selection_handles = [resize_handle, rotate_handle]
        self._place_selection_handles(target)

    def _place_selection_handles(self, target: EditableItem) -> None:
        """Resize at the target's bounding-box top-right corner, rotate
        just above its top edge."""
        rect = target.path().boundingRect()
        margin = max(rect.height() * 0.15, 0.5)
        for handle in self._selection_handles:
            if handle.kind == "resize":
                handle.place_at(rect.topRight())
            else:
                handle.place_at(QPointF(rect.center().x(), rect.top() - margin))

    def _settle_handle_gesture(self) -> None:
        """After a resize/rotate handle commits, fold the result into the
        selected item itself and put the handles back on its edge — a
        real bug otherwise: the dragged handle stayed wherever the mouse
        let go and the other stayed at the pre-gesture bounding box, both
        drifting away from the object, since a handle commit deliberately
        doesn't rebuild the scene (see `SelectionHandle`). Only this one
        item is updated in place, so nothing is destroyed mid-event: its
        path is regenerated from the freshly recomputed geometry and the
        Qt-level preview rotation/scale is cleared. That also means a
        second gesture starts from what's actually drawn, instead of
        overwriting the first gesture's leftover preview transform and
        snapping the object back."""
        if not self._selection_handles:
            return
        target = self._selection_handles[0].target
        geom = self.session.resolved.get(target.scene_object.id).geometry
        page_height = self.session.doc.page_height
        target.setRotation(0)
        target.setScale(1)
        target.setPath(_path_for_geometry(geom, page_height))
        if target.joints_item is not None:  # re-lay the bricks for the new size/angle
            resolved = self.session.resolved.get(target.scene_object.id)
            material = self.session.materials.resolve(resolved.material)
            joints = _paver_joints_path(geom, material, resolved.pattern, page_height, self.session.doc.units)
            if joints is not None:
                target.joints_item.setPath(joints)
        c = geom.centroid
        target.centroid = QPointF(c.x, page_height - c.y)
        self._place_selection_handles(target)

    def _show_selected_size(self, factor: float = 1.0) -> None:
        """The selected object's size from its committed geometry, times
        `factor` — 1.0 normally, the in-progress ratio during a resize drag."""
        if not self._selected_id:
            return
        from dataclasses import replace

        from .dimensions import object_dimensions

        dims = object_dimensions(self.session.doc.get(self._selected_id))
        if dims is not None and factor != 1.0:
            dims = replace(
                dims,
                width=dims.width * factor if dims.width else None,
                height=dims.height * factor if dims.height else None,
            )
        geom = self.session.resolved.get(self._selected_id).geometry
        self._panel.show_size(dims, self.session.doc.units, dimensions_text(geom, factor, self.session.doc.units))

    def _show_selected_solid(self) -> None:
        from .solids import effective_solid

        if self._selected_id:
            solid = effective_solid(self.session.resolved.get(self._selected_id), self.session.materials)
            self._panel.show_solid(solid, self.session.doc.units)

    def _on_solid_edited(self, which: str, value: float) -> None:
        """A height or base typed into the Height row: saved on the object
        itself (overriding what it inherited), for the 3D view."""
        if not self._selected_id:
            return
        try:
            self.session.set_solid(self._selected_id, **{which: value})
        except ValueError as exc:
            self.statusBar().showMessage(f"Can't set height: {exc}")
            self._show_selected_solid()
            return
        self._rebuild_scene()

    def _on_size_edited(self, which: str, value: float) -> None:
        """A width/height (or diameter) typed into the Size row: reshape the
        object in that direction only, then rebuild so everything —
        handles, joints, the readout — reflects the new shape."""
        if not self._selected_id:
            return
        from .dimensions import object_dimensions

        dims = object_dimensions(self.session.doc.get(self._selected_id))
        if dims is not None and dims.diameter_only:
            which = "width"  # one value; the resize treats it as the diameter
        try:
            self.session.set_dimensions(self._selected_id, **{which: value})
        except ValueError as exc:
            self.statusBar().showMessage(f"Can't resize: {exc}")
            self._show_selected_size()
            return
        self._rebuild_scene()

    def _on_handle_resized(self, value: float) -> None:
        if not self._selected_id:
            return
        self.session.set_scale(self._selected_id, value)
        self._settle_handle_gesture()
        self._show_selected_size()
        self._panel.scale_spin.blockSignals(True)
        self._panel.scale_spin.setValue(value)
        self._panel.scale_spin.blockSignals(False)

    def _on_handle_rotated(self, value: float) -> None:
        if not self._selected_id:
            return
        self.session.set_rotation(self._selected_id, value)
        self._settle_handle_gesture()
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

    def _on_pattern_changed(self, index: int) -> None:
        if self._selected_id:
            self.session.set_pattern(self._selected_id, self._panel.pattern_combo.itemData(index))
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
