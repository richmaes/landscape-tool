"""Graphical editor (M8) — first vertical slice.

This is *not* the whole editor. It's the thinnest real step toward one: a
window that loads a scene, shows the same flat-mode picture `render_flat`
produces, and lets the designer pan and zoom. Selection, move/resize/
rotate, live rule-checker feedback, undo/redo, autosave, and round-trip
saving are all still open — see the M8 checklist in TODO.md for what's
actually done versus still ahead.

Uses PySide6 (`QGraphicsScene`/`QGraphicsView`), per the UI-stack decision
recorded in TODO.md: `QGraphicsItem` gives interactive selection and
transform handles largely for free, which a plain Tk `Canvas` doesn't, and
that's what turns this slice into the rest of M8 without switching stacks.

Every object becomes its own `QGraphicsItem` (tagged with its scene id via
`setData(0, ...)`) rather than one big painted picture, since M8's later
steps (select, move, resize, rotate) all need to hit-test and manipulate
individual objects, not a flattened image.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMainWindow,
)
from shapely.geometry.base import BaseGeometry

from .geometry import ResolvedObject, ResolvedScene
from .materials import Material, MaterialLibrary

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


def _add_material_item(scene: QGraphicsScene, obj: ResolvedObject, material: Material, page_height: float) -> None:
    path = _path_for_geometry(obj.geometry, page_height)
    item = QGraphicsPathItem(path)
    item.setData(_OBJECT_ID_ROLE, obj.id)

    fill = QColor(material.color)
    is_area = obj.geometry.geom_type in ("Polygon", "MultiPolygon")
    weight = material.edge.get("weight", 1.0) or 0.0
    edge = QColor(material.edge["color"]) if material.edge.get("color") else _darken(fill)

    item.setBrush(QBrush(fill) if is_area else QBrush(Qt.NoBrush))
    item.setPen(QPen(edge, weight) if weight > 0 else QPen(Qt.NoPen))
    scene.addItem(item)


def _add_annotation_item(scene: QGraphicsScene, obj: ResolvedObject, label: str, page_height: float) -> None:
    """Annotations and keepout zones: dashed outline, no fill, a text
    label at the centroid — mirrors `render_flat._draw_annotation`."""
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
) -> QGraphicsScene:
    """The same picture `render_flat` draws, as interactive QGraphicsItems
    instead of a flattened cairo surface."""
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
        _add_material_item(gscene, obj, material, page_height)

    return gscene


class SceneGraphicsView(QGraphicsView):
    """Pan (drag) and zoom (wheel) over a `QGraphicsScene` — the "fast
    low-resolution preview" M8 asks for; layer/mode toggling is still
    ahead since there's only one render mode (flat) to toggle to yet."""

    def __init__(self, scene: QGraphicsScene | None = None):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class EditorWindow(QMainWindow):
    def __init__(self, materials_path: str | Path = "assets/materials.yaml"):
        super().__init__()
        self.setWindowTitle("Landscape Editor")
        self._materials_path = materials_path
        self._view = SceneGraphicsView()
        self.setCentralWidget(self._view)
        self.resize(1000, 800)

    def load_scene(self, scene_path: str | Path, show_annotations: bool = False) -> None:
        from .geometry import resolve_scene
        from .materials import load_materials
        from .scene_io import load_scene as load_scene_doc

        doc = load_scene_doc(scene_path)
        resolved = resolve_scene(doc)
        materials = load_materials(self._materials_path)
        gscene = build_graphics_scene(resolved, materials, doc.page_height, show_annotations)
        self._view.setScene(gscene)
        self._view.fitInView(gscene.itemsBoundingRect(), Qt.KeepAspectRatio)
        self.setWindowTitle(f"Landscape Editor — {Path(scene_path).name}")
