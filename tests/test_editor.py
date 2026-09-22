import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # must be set before any Qt import

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsPathItem, QGraphicsSimpleTextItem
from shapely.geometry import box

from landscape.editor import EditableItem, EditorWindow, build_graphics_scene
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


def test_material_items_are_editable_when_doc_given(qapp):
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="red")])
    from landscape.schema import SceneDocument, SceneObject
    from landscape.schema import Rect as RectPrimitive

    doc = SceneDocument(
        page_width=10, page_height=10, scale=1,
        objects=[SceneObject(id="a", primitive=RectPrimitive(x=0, y=0, width=2, height=2), material="red")],
    )
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, doc=doc)
    item = gscene.items()[0]
    assert isinstance(item, EditableItem)
    assert item.scene_object is doc.get("a")


def test_annotations_are_never_editable_even_with_doc(qapp):
    from landscape.schema import SceneDocument, SceneObject
    from landscape.schema import Rect as RectPrimitive

    doc = SceneDocument(
        page_width=10, page_height=10, scale=1,
        objects=[
            SceneObject(id="m", primitive=RectPrimitive(x=0, y=0, width=2, height=2), annotation=True)
        ],
    )
    scene = ResolvedScene(objects=[_obj("m", box(0, 0, 2, 2), annotation=True)])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, doc=doc, show_annotations=True)
    item = [i for i in gscene.items() if isinstance(i, QGraphicsPathItem)][0]
    assert not isinstance(item, EditableItem)


def test_dragging_an_item_updates_the_document_transform(qapp):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    window.load_scene(EXAMPLE_SCENE, show_annotations=True)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    before = window._doc.get("shed").transform
    tx0, ty0 = before.tx, before.ty

    shed.setPos(QPointF(2, 3))  # Qt coords: +x east, +y *south*

    after = window._doc.get("shed").transform
    assert after.tx == pytest.approx(tx0 + 2)
    assert after.ty == pytest.approx(ty0 - 3)  # y flipped back to the scene's +y-north convention
    # the move is baked into the item's own path, not left in Qt's pos(),
    # so a later rebuild never double-counts it
    assert shed.pos() == QPointF(0, 0)


def test_rotation_panel_edit_updates_document_and_rebuilds(qapp):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    window.load_scene(EXAMPLE_SCENE, show_annotations=True)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.rotation_spin.setValue(45)

    assert window._doc.get("shed").transform.rotation == 45


def test_selection_persists_across_a_rebuild(qapp):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    window.load_scene(EXAMPLE_SCENE, show_annotations=True)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.rotation_spin.setValue(10)  # triggers a rebuild internally

    assert window._selected_id == "shed"
    new_shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    assert new_shed.isSelected()


def test_material_panel_edit_updates_document(qapp):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    window.load_scene(EXAMPLE_SCENE, show_annotations=True)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.material_combo.setCurrentText("water")

    assert window._doc.get("shed").material == "water"


def test_scale_panel_edit_updates_document(qapp):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    window.load_scene(EXAMPLE_SCENE, show_annotations=True)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.scale_spin.setValue(2.5)

    assert window._doc.get("shed").transform.scale == 2.5


def test_deselecting_clears_the_panel(qapp):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    window.load_scene(EXAMPLE_SCENE, show_annotations=True)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)
    assert window._panel.isEnabled()

    shed.setSelected(False)

    assert window._selected_id is None
    assert not window._panel.isEnabled()
