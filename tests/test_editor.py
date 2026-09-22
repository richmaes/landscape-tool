import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # must be set before any Qt import

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGraphicsPathItem, QGraphicsSimpleTextItem
from shapely.geometry import box

from landscape.editor import EditorWindow, build_graphics_scene
from landscape.geometry import ResolvedObject, ResolvedScene
from landscape.materials import Material, MaterialLibrary

EXAMPLE_SCENE = Path(__file__).parent.parent / "scenes" / "example.yaml"
DEFAULT_MATERIALS = Path(__file__).parent.parent / "assets" / "materials.yaml"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _obj(id, geom, material=None, z=0, annotation=False, rule=None):
    return ResolvedObject(id=id, geometry=geom, material=material, layer="default", z=z, annotation=annotation, rule=rule)


def _tiny_library():
    return MaterialLibrary(materials={"red": Material(id="red", name="Red", color="#FF0000")})


def test_build_graphics_scene_creates_one_item_per_material_object(qapp):
    scene = ResolvedScene(
        objects=[_obj("a", box(0, 0, 2, 2), material="red"), _obj("b", box(3, 3, 5, 5), material="red")]
    )
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    path_items = [i for i in gscene.items() if isinstance(i, QGraphicsPathItem)]
    assert len(path_items) == 2


def test_material_item_is_tagged_with_object_id(qapp):
    scene = ResolvedScene(objects=[_obj("bed", box(0, 0, 2, 2), material="red")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    item = gscene.items()[0]
    assert item.data(0) == "bed"


def test_annotation_item_has_no_fill_and_dashed_pen(qapp):
    scene = ResolvedScene(objects=[_obj("marker", box(0, 0, 2, 2), material="red", annotation=True)])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, show_annotations=True)
    path_items = [i for i in gscene.items() if isinstance(i, QGraphicsPathItem)]
    assert len(path_items) == 1
    item = path_items[0]
    assert item.brush().style() == Qt.NoBrush
    assert item.pen().style() == Qt.DashLine


def test_annotation_item_gets_a_text_label(qapp):
    scene = ResolvedScene(objects=[_obj("marker", box(0, 0, 2, 2), material="red", annotation=True)])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, show_annotations=True)
    labels = [i for i in gscene.items() if isinstance(i, QGraphicsSimpleTextItem)]
    assert len(labels) == 1
    assert labels[0].text() == "marker"


def test_keepout_zone_labeled_with_its_rule(qapp):
    scene = ResolvedScene(objects=[_obj("zone", box(0, 0, 2, 2), rule="no_burnable_material")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    labels = [i for i in gscene.items() if isinstance(i, QGraphicsSimpleTextItem)]
    assert labels[0].text() == "zone (no_burnable_material)"


def test_annotations_excluded_by_default(qapp):
    scene = ResolvedScene(objects=[_obj("marker", box(0, 0, 2, 2), material="red", annotation=True)])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, show_annotations=False)
    assert len(gscene.items()) == 0


def test_material_item_uses_material_fill_color(qapp):
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="red")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    item = gscene.items()[0]
    assert item.brush().color().name().lower() == "#ff0000"


def test_editor_window_loads_example_scene(qapp):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    window.load_scene(EXAMPLE_SCENE, show_annotations=True)
    assert window._view.scene() is not None
    assert len(window._view.scene().items()) > 0
    assert "example.yaml" in window.windowTitle()


def test_editor_window_items_include_known_object_ids(qapp):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    window.load_scene(EXAMPLE_SCENE, show_annotations=True)
    ids = {item.data(0) for item in window._view.scene().items() if item.data(0)}
    assert "firepit" in ids
    assert "firepit_keepout" in ids
    assert "clearance_marker" in ids
