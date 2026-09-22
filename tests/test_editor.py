import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # must be set before any Qt import

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsSimpleTextItem
from shapely.geometry import box

from landscape.editor import EditableItem, EditorWindow, add_violation_overlays, build_graphics_scene
from landscape.geometry import ResolvedObject, ResolvedScene
from landscape.materials import Material, MaterialLibrary
from landscape.rules import Violation

EXAMPLE_SCENE = Path(__file__).parent.parent / "scenes" / "example.yaml"
BACKYARD_SCENE = Path(__file__).parent.parent / "scenes" / "backyard.yaml"
BACKYARD_RULES = Path(__file__).parent.parent / "rules" / "backyard.yaml"
DEFAULT_MATERIALS = Path(__file__).parent.parent / "assets" / "materials.yaml"


def _obj(id, geom, material=None, z=0, annotation=False, rule=None):
    return ResolvedObject(id=id, geometry=geom, material=material, layer="default", z=z, annotation=annotation, rule=rule)


def _tiny_library():
    return MaterialLibrary(materials={"red": Material(id="red", name="Red", color="#FF0000")})


def _open_editor(qtbot, show_annotations: bool = True) -> EditorWindow:
    """A loaded EditorWindow, registered with qtbot so pytest-qt owns its
    teardown — relying on Python's GC to clean up QGraphicsScene/QWidget
    objects (which have no Qt-parent to enforce C++ destruction order)
    across dozens of tests in one process is what caused a real,
    reproducible segfault during this feature's development."""
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(EXAMPLE_SCENE, show_annotations=show_annotations)
    return window


def test_build_graphics_scene_creates_one_item_per_material_object(qtbot):
    scene = ResolvedScene(
        objects=[_obj("a", box(0, 0, 2, 2), material="red"), _obj("b", box(3, 3, 5, 5), material="red")]
    )
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    path_items = [i for i in gscene.items() if isinstance(i, QGraphicsPathItem)]
    assert len(path_items) == 2


def test_material_item_is_tagged_with_object_id(qtbot):
    scene = ResolvedScene(objects=[_obj("bed", box(0, 0, 2, 2), material="red")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    item = gscene.items()[0]
    assert item.data(0) == "bed"


def test_annotation_item_has_no_fill_and_dashed_pen(qtbot):
    scene = ResolvedScene(objects=[_obj("marker", box(0, 0, 2, 2), material="red", annotation=True)])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, show_annotations=True)
    path_items = [i for i in gscene.items() if isinstance(i, QGraphicsPathItem)]
    assert len(path_items) == 1
    item = path_items[0]
    assert item.brush().style() == Qt.NoBrush
    assert item.pen().style() == Qt.DashLine


def test_annotation_item_gets_a_text_label(qtbot):
    scene = ResolvedScene(objects=[_obj("marker", box(0, 0, 2, 2), material="red", annotation=True)])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, show_annotations=True)
    labels = [i for i in gscene.items() if isinstance(i, QGraphicsSimpleTextItem)]
    assert len(labels) == 1
    assert labels[0].text() == "marker"


def test_keepout_zone_labeled_with_its_rule(qtbot):
    scene = ResolvedScene(objects=[_obj("zone", box(0, 0, 2, 2), rule="no_burnable_material")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    labels = [i for i in gscene.items() if isinstance(i, QGraphicsSimpleTextItem)]
    assert labels[0].text() == "zone (no_burnable_material)"


def test_annotations_excluded_by_default(qtbot):
    scene = ResolvedScene(objects=[_obj("marker", box(0, 0, 2, 2), material="red", annotation=True)])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, show_annotations=False)
    assert len(gscene.items()) == 0


def test_material_item_uses_material_fill_color(qtbot):
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="red")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    item = gscene.items()[0]
    assert item.brush().color().name().lower() == "#ff0000"


def test_editor_window_loads_example_scene(qtbot):
    window = _open_editor(qtbot)
    assert window._view.scene() is not None
    assert len(window._view.scene().items()) > 0
    assert "example.yaml" in window.windowTitle()


def test_editor_window_items_include_known_object_ids(qtbot):
    window = _open_editor(qtbot)
    ids = {item.data(0) for item in window._view.scene().items() if item.data(0)}
    assert "firepit" in ids
    assert "firepit_keepout" in ids
    assert "clearance_marker" in ids


def test_material_items_are_editable_when_doc_given(qtbot):
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


def test_annotations_are_never_editable_even_with_doc(qtbot):
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


def test_dragging_an_item_updates_the_document_transform(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    before = window.session.doc.get("shed").transform
    tx0, ty0 = before.tx, before.ty

    shed.setPos(QPointF(2, 3))  # Qt coords: +x east, +y *south*

    after = window.session.doc.get("shed").transform
    assert after.tx == pytest.approx(tx0 + 2)
    assert after.ty == pytest.approx(ty0 - 3)  # y flipped back to the scene's +y-north convention
    # the move is baked into the item's own path, not left in Qt's pos(),
    # so a later rebuild never double-counts it
    assert shed.pos() == QPointF(0, 0)


def test_rotation_panel_edit_updates_document_and_rebuilds(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.rotation_spin.setValue(45)

    assert window.session.doc.get("shed").transform.rotation == 45


def test_selection_persists_across_a_rebuild(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.rotation_spin.setValue(10)  # triggers a rebuild internally

    assert window._selected_id == "shed"
    new_shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    assert new_shed.isSelected()


def test_material_panel_edit_updates_document(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.material_combo.setCurrentText("water")

    assert window.session.doc.get("shed").material == "water"


def test_scale_panel_edit_updates_document(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.scale_spin.setValue(2.5)

    assert window.session.doc.get("shed").transform.scale == 2.5


def test_save_unchanged_scene_is_byte_identical(qtbot, tmp_path):
    window = _open_editor(qtbot)
    out = tmp_path / "roundtrip.yaml"
    window.save_scene(out)
    assert out.read_text() == EXAMPLE_SCENE.read_text()


def test_save_after_edit_only_touches_the_edited_object(qtbot, tmp_path):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)
    window._panel.rotation_spin.setValue(45)

    out = tmp_path / "edited.yaml"
    window.save_scene(out)

    # every line belonging to an object other than 'shed' is untouched.
    # The rewritten transform switches from flow to block style, so its
    # sub-keys (now their own lines) need excluding too, not just the
    # line that says "transform".
    touched = ("shed", "transform", "tx:", "ty:", "rotation:", "scale:")
    unrelated_original = [l for l in EXAMPLE_SCENE.read_text().splitlines() if not any(t in l for t in touched)]
    unrelated_saved = [l for l in out.read_text().splitlines() if not any(t in l for t in touched)]
    assert unrelated_original == unrelated_saved

    from landscape.scene_io import load_scene as parse_saved

    reloaded = parse_saved(out)
    assert reloaded.get("shed").transform.rotation == 45


def test_save_after_move_writes_transform_back(qtbot, tmp_path):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setPos(QPointF(2, 3))

    out = tmp_path / "moved.yaml"
    window.save_scene(out)

    from landscape.scene_io import load_scene as parse_saved

    reloaded = parse_saved(out)
    t = reloaded.get("shed").transform
    assert t.tx == pytest.approx(2.5)  # original 0.5 + 2
    assert t.ty == pytest.approx(-3)  # original 0 - 3


def test_save_after_material_change_writes_material_back(qtbot, tmp_path):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)
    window._panel.material_combo.setCurrentText("water")

    out = tmp_path / "material.yaml"
    window.save_scene(out)

    from landscape.scene_io import load_scene as parse_saved

    assert parse_saved(out).get("shed").material == "water"


def test_save_to_explicit_path_does_not_touch_original(qtbot, tmp_path):
    original_bytes = EXAMPLE_SCENE.read_bytes()
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)
    window._panel.rotation_spin.setValue(90)

    window.save_scene(tmp_path / "elsewhere.yaml")

    assert EXAMPLE_SCENE.read_bytes() == original_bytes


def test_save_action_writes_the_file(qtbot, tmp_path, monkeypatch):
    window = _open_editor(qtbot)
    out = tmp_path / "via_menu.yaml"
    monkeypatch.setattr(window.session, "scene_path", out)

    save_action = next(a for a in window.menuBar().actions()[0].menu().actions() if a.text() == "&Save")
    save_action.trigger()

    assert out.exists()
    assert out.read_text() == EXAMPLE_SCENE.read_text()


def test_export_action_writes_a_rendered_file(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    window = _open_editor(qtbot)
    out = tmp_path / "via_menu.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "PNG (*.png)"))

    export_action = next(a for a in window.menuBar().actions()[0].menu().actions() if a.text() == "&Export…")
    export_action.trigger()

    assert out.exists() and out.stat().st_size > 0
    assert "Exported to" in window.statusBar().currentMessage()


def test_export_action_cancelled_dialog_does_nothing(qtbot, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    window = _open_editor(qtbot)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))

    export_action = next(a for a in window.menuBar().actions()[0].menu().actions() if a.text() == "&Export…")
    export_action.trigger()  # must not raise, must not touch the status bar

    assert window.statusBar().currentMessage() == ""


def test_export_action_shows_warning_on_bad_extension(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    window = _open_editor(qtbot)
    out = tmp_path / "via_menu.jpg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "JPEG (*.jpg)"))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    export_action = next(a for a in window.menuBar().actions()[0].menu().actions() if a.text() == "&Export…")
    export_action.trigger()

    assert len(warnings) == 1
    assert not out.exists()


def test_layers_menu_lists_scene_layers(qtbot):
    window = _open_editor(qtbot)
    assert [a.text() for a in window._layers_menu.actions()] == ["ground", "structures", "annotation"]
    assert all(a.isChecked() for a in window._layers_menu.actions())


def test_hiding_a_layer_removes_its_objects(qtbot):
    window = _open_editor(qtbot)
    before_ids = {i.data(0) for i in window._view.scene().items() if i.data(0)}
    assert "shed" in before_ids  # 'shed' is on the 'structures' layer

    window._on_layer_toggled("structures", False)

    after_ids = {i.data(0) for i in window._view.scene().items() if i.data(0)}
    assert "shed" not in after_ids
    assert "site_circle" in after_ids  # 'ground' layer untouched


def test_showing_a_hidden_layer_restores_its_objects(qtbot):
    window = _open_editor(qtbot)
    window._on_layer_toggled("structures", False)
    window._on_layer_toggled("structures", True)

    ids = {i.data(0) for i in window._view.scene().items() if i.data(0)}
    assert "shed" in ids


def test_hidden_layers_reset_on_new_load(qtbot):
    window = _open_editor(qtbot)
    window._on_layer_toggled("structures", False)
    assert window._hidden_layers == {"structures"}

    window.load_scene(EXAMPLE_SCENE, show_annotations=True)

    assert window._hidden_layers == set()


def test_add_violation_overlays_highlights_named_objects(qtbot):
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="red")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    violation = Violation(rule_id="r1", object_ids=["a"], message="test violation", location=(1, 1))

    add_violation_overlays(gscene, [violation], page_height=10)

    highlights = [
        i
        for i in gscene.items()
        if isinstance(i, QGraphicsPathItem) and i.data(0) is None and i.toolTip()
    ]
    assert len(highlights) == 1
    assert "test violation" in highlights[0].toolTip()
    assert highlights[0].pen().style() == Qt.DashLine


def test_add_violation_overlays_adds_a_marker_with_tooltip(qtbot):
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="red")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    violation = Violation(rule_id="r1", object_ids=["a"], message="test violation", location=(1, 1))

    before = len(gscene.items())
    add_violation_overlays(gscene, [violation], page_height=10)

    new_items = [i for i in gscene.items() if i.toolTip()]
    assert len(gscene.items()) > before
    assert any("[r1] test violation" in i.toolTip() for i in new_items)


def test_no_overlays_added_when_no_violations(qtbot):
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="red")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    before = len(gscene.items())

    add_violation_overlays(gscene, [], page_height=10)

    assert len(gscene.items()) == before


def test_editor_computes_violations_against_real_backyard_scene(qtbot):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS, rules_path=BACKYARD_RULES)
    qtbot.addWidget(window)
    window.load_scene(BACKYARD_SCENE, show_annotations=True)

    assert {v.rule_id for v in window.session.violations} == {
        "no_burnable_in_firepit_keepout",
        "firepit_keepout_concentric",
        "firepit_keepout_contained_by_site",
    }
    assert "3 rule violation" in window.statusBar().currentMessage()


def test_editor_without_rules_path_has_no_violations(qtbot):
    window = _open_editor(qtbot)  # no rules_path given
    assert window.session.violations == []
    assert window.statusBar().currentMessage() == ""


def test_violations_recompute_after_an_edit(qtbot):
    window = EditorWindow(materials_path=DEFAULT_MATERIALS, rules_path=BACKYARD_RULES)
    qtbot.addWidget(window)
    window.load_scene(BACKYARD_SCENE, show_annotations=True)
    assert len(window.session.violations) == 3

    # recentering the keepout on the firepit should clear the concentricity
    # violation specifically
    keepout = window.session.doc.get("firepit_keepout")
    firepit = window.session.doc.get("firepit")
    dx = firepit.primitive.cx - keepout.primitive.shape.cx
    dy = firepit.primitive.cy - keepout.primitive.shape.cy
    keepout.transform.tx += dx
    keepout.transform.ty += dy
    window.session.sync_object("firepit_keepout")
    window.session.recompute()  # direct doc mutation, not via session.set_*, so recompute explicitly
    window._rebuild_scene()

    assert "firepit_keepout_concentric" not in {v.rule_id for v in window.session.violations}


def test_deselecting_clears_the_panel(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)
    assert window._panel.isEnabled()

    shed.setSelected(False)

    assert window._selected_id is None
    assert not window._panel.isEnabled()
