import math
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # must be set before any Qt import

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsPathItem, QGraphicsSimpleTextItem, QGraphicsView
from shapely.geometry import box

from landscape.editor import (
    BACKGROUND_COLOR,
    LINE_COLOR,
    EditableItem,
    EditorWindow,
    SceneGraphicsView,
    _line_width_for_zoom,
    add_violation_overlays,
    build_graphics_scene,
)
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


def _scene_copy(path: Path) -> Path:
    """A private copy of a scene fixture in its own temp directory, same
    filename. Editor tests routinely mutate the loaded scene, which now
    (since autosave landed) writes a `.autosave` sidecar next to
    whatever path was loaded — loading the real fixture directly would
    litter the repo with those on every test run. Not pytest's `tmp_path`
    fixture: threading it through every one of ~50 call sites across
    this file would be a much bigger change than the problem warrants."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="landscape-test-"))
    copy_path = tmp_dir / path.name
    shutil.copy(path, copy_path)
    return copy_path


def _open_editor(qtbot, show_annotations: bool = True) -> EditorWindow:
    """A loaded EditorWindow, registered with qtbot so pytest-qt owns its
    teardown — relying on Python's GC to clean up QGraphicsScene/QWidget
    objects (which have no Qt-parent to enforce C++ destruction order)
    across dozens of tests in one process is what caused a real,
    reproducible segfault during this feature's development."""
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(_scene_copy(EXAMPLE_SCENE), show_annotations=show_annotations)
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


def test_material_item_outline_is_the_uniform_charcoal_color_not_the_materials_own_edge_color(qtbot):
    """Visual redesign, phase 1: every shape gets the same dark charcoal
    outline for now, regardless of what its own material specifies —
    a `Material` with an explicit (very different) edge color must
    still render with `LINE_COLOR`, not that color."""
    library = MaterialLibrary(
        materials={"blue_edged": Material(id="blue_edged", name="Blue-edged", color="#FF0000", edge={"weight": 2.0, "color": "#0000FF"})}
    )
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="blue_edged")])
    gscene = build_graphics_scene(scene, library, page_height=10)
    item = gscene.items()[0]
    assert item.pen().color().name().lower() == LINE_COLOR.name().lower()


def test_material_item_uses_the_given_line_width(qtbot):
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="red")])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10, line_width=0.42)
    item = gscene.items()[0]
    assert item.pen().widthF() == pytest.approx(0.42)


def test_build_graphics_scene_has_an_off_white_background(qtbot):
    scene = ResolvedScene(objects=[])
    gscene = build_graphics_scene(scene, _tiny_library(), page_height=10)
    assert gscene.backgroundBrush().color().name().lower() == BACKGROUND_COLOR.name().lower()


def test_scene_graphics_view_has_an_off_white_background(qtbot):
    view = SceneGraphicsView()
    qtbot.addWidget(view)
    assert view.backgroundBrush().color().name().lower() == BACKGROUND_COLOR.name().lower()


def test_line_width_for_zoom_converts_target_pixels_into_scene_units():
    from landscape.editor import LINE_WIDTH_PX

    assert _line_width_for_zoom(1.0) == pytest.approx(LINE_WIDTH_PX)
    assert _line_width_for_zoom(2.0) == pytest.approx(LINE_WIDTH_PX / 2)
    assert _line_width_for_zoom(0.5) == pytest.approx(LINE_WIDTH_PX / 0.5)


def test_rebuild_scene_recalculates_line_width_for_the_views_current_zoom(qtbot):
    """The whole point of `_line_width_for_zoom`: line thickness should
    "change depending on magnification" (Rich's own words), so a rebuild
    that happens while the view is more zoomed in must produce a
    correspondingly thinner scene-unit outline (still ~3 screen px)."""
    window = _open_editor(qtbot)
    item = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    width_before = item.pen().widthF()

    window._view.scale(2.0, 2.0)
    window._rebuild_scene()

    item_after = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    assert item_after.pen().widthF() == pytest.approx(width_before / 2, rel=0.01)


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


# --- real Qt input events (wheel zoom, space-bar pan) ---------------------
#
# Every other interaction test in this file drives the same code a real
# gesture would (setPos() through itemChange, direct method calls like
# end_drag()) rather than a real mouse/keyboard event — reliable and fast,
# but it never exercises Qt's actual event dispatch. These do: QTest.
# keyPress/keyRelease route through the real focus/dispatch machinery, and
# a manually-constructed QWheelEvent is sent via QApplication.sendEvent()
# to the view's *viewport* widget — where Qt actually delivers wheel
# events for a QGraphicsView — not called as a bare method on the view.


def _wheel_event(delta_y: int) -> QWheelEvent:
    return QWheelEvent(
        QPointF(50, 50),
        QPointF(50, 50),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )


def test_real_wheel_event_scroll_up_zooms_in(qtbot):
    window = _open_editor(qtbot)
    before = window._view.transform().m11()

    QApplication.sendEvent(window._view.viewport(), _wheel_event(120))

    assert window._view.transform().m11() > before


def test_real_wheel_event_scroll_down_zooms_out(qtbot):
    window = _open_editor(qtbot)
    before = window._view.transform().m11()

    QApplication.sendEvent(window._view.viewport(), _wheel_event(-120))

    assert window._view.transform().m11() < before


def test_zoom_per_tick_matches_the_configured_rate(qtbot):
    from landscape.editor import SceneGraphicsView

    window = _open_editor(qtbot)
    before = window._view.transform().m11()

    QApplication.sendEvent(window._view.viewport(), _wheel_event(120))

    assert window._view.transform().m11() == pytest.approx(before * SceneGraphicsView.ZOOM_PER_TICK)


def test_zoom_anchors_on_viewport_center_when_nothing_is_selected(qtbot):
    window = _open_editor(qtbot)
    window.resize(800, 600)
    window.show()
    window._view.scale(5.0, 5.0)
    anchor_point = window._view.mapToScene(window._view.viewport().rect().center())
    pixel_before = window._view.mapFromScene(anchor_point)

    QApplication.sendEvent(window._view.viewport(), _wheel_event(120))

    pixel_after = window._view.mapFromScene(anchor_point)
    assert (pixel_after - pixel_before).manhattanLength() <= 1


def test_zoom_anchor_stays_the_viewport_center_even_with_an_object_selected(qtbot):
    """Simplified on request, 2026-09-23: zoom used to anchor on the
    *selected object's* center instead of the viewport center whenever
    exactly one object was selected — Rich's own earlier request, made
    when adding the previous zoom fix. After using it for real, he asked
    to simplify: the anchor point silently jumping between "the viewport
    center" and "some object's center" the moment something got
    selected or deselected was itself part of what read as "zoom out
    seems to scale wildly and then recenter" — an inconsistency, not
    just a numerical bug. Now the anchor is *always* the viewport
    center ("the center of the image"), regardless of selection —
    matching his new, explicit instruction ("on zoom in, we should zoom
    in on the center of the image... keep it simple for now"). This
    test is the direct regression guard for that: selecting `shed`
    first must not change where the zoom anchors."""
    window = _open_editor(qtbot)
    window.resize(800, 600)
    window.show()
    window._view.scale(5.0, 5.0)
    _select_only(window, "shed")
    viewport_center_scene = window._view.mapToScene(window._view.viewport().rect().center())
    pixel_before = window._view.mapFromScene(viewport_center_scene)

    QApplication.sendEvent(window._view.viewport(), _wheel_event(120))

    pixel_after = window._view.mapFromScene(viewport_center_scene)
    assert (pixel_after - pixel_before).manhattanLength() <= 1


def test_real_wheel_event_zoom_out_past_the_initial_fit_stays_smooth(qtbot):
    """The actual bug Rich reported: "zoom out seems to scale wildly and
    then recenter." Zooming out from a fresh load (no manual zoom-in
    first) crosses the point where the whole scene already fits inside
    the viewport — exactly the edge case the *old* scrollbar-based
    anchor correction admitted it couldn't handle (nothing to scroll to,
    so nothing for the correction to adjust) — Qt's own built-in
    `AnchorViewCenter` handles it instead. Drives 40 real wheel-event
    zoom-out ticks (well past that threshold: the view ends up at a
    fraction of its starting zoom) and asserts no single tick's drift
    at the viewport center is anything close to "wild" — a generous
    bound given some genuine sub-pixel drift is normal (integer-pixel
    quantization of the viewport's center, mapped through a
    continuously-changing zoom transform, was never going to land on
    the exact same scene point every single tick)."""
    window = _open_editor(qtbot)
    window.resize(800, 600)
    window.show()

    max_drift = 0.0
    for _ in range(40):
        center_before = window._view.mapToScene(window._view.viewport().rect().center())
        QApplication.sendEvent(window._view.viewport(), _wheel_event(-120))
        center_after = window._view.mapToScene(window._view.viewport().rect().center())
        drift = center_after - center_before
        max_drift = max(max_drift, (drift.x() ** 2 + drift.y() ** 2) ** 0.5)

    assert max_drift < 1.0  # empirically ~0.5 at worst; "wild" would be many scene units


def test_real_space_keypress_enables_pan_mode(qtbot):
    window = _open_editor(qtbot)
    window._view.setFocus()
    assert window._view.dragMode() == QGraphicsView.NoDrag

    QTest.keyPress(window._view, Qt.Key_Space)

    assert window._view.dragMode() == QGraphicsView.ScrollHandDrag


def test_real_space_keyrelease_restores_select_mode(qtbot):
    window = _open_editor(qtbot)
    window._view.setFocus()
    QTest.keyPress(window._view, Qt.Key_Space)
    assert window._view.dragMode() == QGraphicsView.ScrollHandDrag

    QTest.keyRelease(window._view, Qt.Key_Space)

    assert window._view.dragMode() == QGraphicsView.NoDrag


def test_real_keypress_of_another_key_does_not_enable_pan_mode(qtbot):
    window = _open_editor(qtbot)
    window._view.setFocus()

    QTest.keyPress(window._view, Qt.Key_A)

    assert window._view.dragMode() == QGraphicsView.NoDrag


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


def test_annotations_are_editable_along_their_outline_only(qtbot):
    """Annotations used to be deliberately non-editable; Rich needs to
    select and move them (the ground-cover box, the firepit keepout), so
    with a `doc` they're `EditableItem`s now — but only the outline is
    clickable, never the empty interior."""
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
    assert isinstance(item, EditableItem)
    # Qt y-down: the 2x2 box spans y 8..10 in scene coords
    assert item.shape().contains(QPointF(0, 9))  # on the west edge
    assert not item.shape().contains(QPointF(1, 9))  # the empty middle
    # the whole hit band, including the part just outside the line, is hit-testable
    assert item.boundingRect().contains(item.shape().boundingRect())


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


def test_real_multi_step_mouse_drag_moves_by_exactly_the_mouse_distance(qtbot):
    """A real, confirmed bug, the third in this same family (rotate
    handle, resize handle, and now plain object move) — found only by
    driving a drag with *several* real `QTest.mouseMove` events instead
    of one big jump. Rich's report: "when I move an object, it seems to
    accelerate beyond the cursor off the page."

    Root cause: `EditableItem.itemChange` always vetoes Qt's own `pos()`
    back to its original (frozen) value — deliberately, since this class
    tracks position through `scene_object.transform`/the path instead
    (see the class docstring). Qt's *default* `mouseMoveEvent`, on every
    move event, recomputes the new position as `press-time pos() +
    (current mouse scenePos - press-time mouse scenePos)` — the
    cumulative offset since press, referenced against its own cached
    `pos()`. Since that `pos()` never actually advances (it's vetoed
    every time), Qt recomputes that same growing cumulative offset on
    every subsequent event too, and `itemChange`'s `delta = value -
    self.pos()` reads the whole cumulative amount as if it were just
    this event's incremental step — applying it on top of what's
    already been applied, every single event. A single-jump drag
    (press, one big move, release) never triggers this, since
    compounding needs a *second* event to show up at all.

    Fixed the same way as the rotate/resize handles: `EditableItem` now
    owns its own press/move handling (tracking the mouse's last scene
    position itself and feeding `itemChange` a true incremental
    per-event delta), instead of relying on `QGraphicsItem`'s default."""
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    window._view.scene().clearSelection()
    shed.setSelected(True)
    tx_before, ty_before = window.session.doc.get("shed").transform.tx, window.session.doc.get("shed").transform.ty

    page_height = window.session.doc.page_height
    start = QPointF(5.5, page_height - 4.0)  # a point on "shed", in Qt/y-flipped coords
    end = start + QPointF(3.0, 0.0)
    _mouse_drag(window._view, start, end, steps=10)

    tx_after, ty_after = window.session.doc.get("shed").transform.tx, window.session.doc.get("shed").transform.ty
    assert tx_after - tx_before == pytest.approx(3.0, abs=0.1)
    assert ty_after - ty_before == pytest.approx(0.0, abs=0.1)


def test_real_multi_step_mouse_drag_is_consistent_regardless_of_distance_from_the_origin(qtbot):
    """The other half of Rich's ask: the same physical drag must produce
    the same translation whether the object sits near the scene origin
    or far from it. The bug above was actually independent of an
    object's position (the frozen reference was always Qt's `pos()`,
    which is always (0, 0) for every `EditableItem` regardless of where
    it's drawn) — but that's exactly the kind of assumption worth
    locking in with a real test rather than trusting it held by
    accident. "shed" sits near the origin (~5, 4); "hot_tub_pad" sits
    far from it (~25-34, 25-34)."""
    window = _open_editor(qtbot)
    page_height = window.session.doc.page_height

    def drag_delta(object_id: str, click_scene_xy: tuple[float, float]) -> QPointF:
        item = next(i for i in window._view.scene().items() if i.data(0) == object_id)
        window._view.scene().clearSelection()
        item.setSelected(True)
        obj = window.session.doc.get(object_id)
        before = QPointF(obj.transform.tx, obj.transform.ty)

        start = QPointF(click_scene_xy[0], page_height - click_scene_xy[1])
        _mouse_drag(window._view, start, start + QPointF(3.0, 0.0), steps=10)

        after = QPointF(obj.transform.tx, obj.transform.ty)
        return after - before

    near_origin_delta = drag_delta("shed", (5.3, 3.8))  # a corner of "shed", clear of its handles
    far_from_origin_delta = drag_delta("hot_tub_pad", (25.3, 25.3))  # a corner not overlapped by "hot_tub"

    assert near_origin_delta.x() == pytest.approx(3.0, abs=0.1)
    assert far_from_origin_delta.x() == pytest.approx(3.0, abs=0.1)
    assert near_origin_delta.x() == pytest.approx(far_from_origin_delta.x(), abs=0.1)


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

    window._panel.material_combo.setCurrentIndex(window._panel.material_combo.findData("water"))

    assert window.session.doc.get("shed").material == "water"


def test_scale_panel_edit_updates_document(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._panel.scale_spin.setValue(2.5)

    assert window.session.doc.get("shed").transform.scale == 2.5


def test_material_combo_shows_swatch_icons(qtbot):
    window = _open_editor(qtbot)
    combo = window._panel.material_combo
    assert combo.count() > 0
    for i in range(combo.count()):
        assert not combo.itemIcon(i).isNull(), f"item {i} ({combo.itemText(i)!r}) has no swatch icon"


def test_material_combo_items_sorted_by_display_name_with_id_as_data(qtbot):
    window = _open_editor(qtbot)
    combo = window._panel.material_combo
    names = [combo.itemText(i) for i in range(combo.count())]
    assert names == sorted(names)
    # display text is the human name ("Water"), not the raw id ("water")
    water_index = combo.findData("water")
    assert water_index >= 0
    assert combo.itemText(water_index) == "Water"


def test_show_object_selects_matching_material_by_id(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)  # shed's material in example.yaml is 'deck'
    assert window._panel.material_combo.currentData() == "deck"


# --- create object -------------------------------------------------------


def test_create_menu_lists_every_creatable_kind(qtbot):
    window = _open_editor(qtbot)
    from landscape.editor_session import CREATABLE_PRIMITIVE_KINDS

    create_menu = next(a for a in window.menuBar().actions() if a.text() == "&Create").menu()
    assert len(create_menu.actions()) == len(CREATABLE_PRIMITIVE_KINDS)


def test_create_object_adds_a_new_selectable_item(qtbot):
    window = _open_editor(qtbot)
    before = len(window._view.scene().items())

    window._on_create_object("circle")

    ids = {i.data(0) for i in window._view.scene().items() if i.data(0)}
    assert "circle_1" in ids
    assert len(window._view.scene().items()) > before


def test_create_object_selects_only_the_new_object(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)

    window._on_create_object("circle")

    selected = window._view.scene().selectedItems()
    assert len(selected) == 1
    assert selected[0].data(0) == "circle_1"
    assert window._selected_id == "circle_1"
    assert window._panel.id_label.text() == "circle_1"


def test_create_object_is_undoable_via_menu(qtbot):
    window = _open_editor(qtbot)
    before = len(window.session.doc.objects)
    window._on_create_object("circle")
    assert window._undo_action.isEnabled()

    window._on_undo()

    assert len(window.session.doc.objects) == before


# --- relation editing ------------------------------------------------------


def _select_only(window: EditorWindow, object_id: str) -> None:
    """Select exactly one item — plain `item.setSelected(True)` adds to
    whatever else is already selected, which breaks _on_selection_changed's
    single-selection assumption (a real trap found while testing this:
    selecting a second item without clearing first silently disables the
    properties panel instead of switching to the new object)."""
    window._view.scene().clearSelection()
    item = next(i for i in window._view.scene().items() if i.data(0) == object_id)
    item.setSelected(True)


def test_relation_type_combo_defaults_to_none(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "deck_west")
    assert window._panel.relation_type_combo.currentData() is None


def test_apply_center_of_relation(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "deck_west")

    window._panel.relation_type_combo.setCurrentIndex(window._panel.relation_type_combo.findData("center_of"))
    window._panel.relation_target_combo.setCurrentIndex(window._panel.relation_target_combo.findText("firepit"))
    window._on_apply_relation()

    from landscape.schema import CenterOf

    assert window.session.doc.get("deck_west").relation == CenterOf(ref="firepit")


def test_reselecting_shows_the_applied_relation(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "deck_west")
    window._panel.relation_type_combo.setCurrentIndex(window._panel.relation_type_combo.findData("center_of"))
    window._panel.relation_target_combo.setCurrentIndex(window._panel.relation_target_combo.findText("firepit"))
    window._on_apply_relation()

    _select_only(window, "firepit")
    _select_only(window, "deck_west")

    assert window._panel.relation_type_combo.currentData() == "center_of"
    assert window._panel.relation_target_combo.currentText() == "firepit"


def test_clear_relation_button(qtbot):
    window = _open_editor(qtbot)
    # deck_east has mirror_of deck_west/about_x=30 already, in example.yaml
    _select_only(window, "deck_east")
    assert window.session.doc.get("deck_east").relation is not None

    window._on_clear_relation()

    assert window.session.doc.get("deck_east").relation is None


def test_apply_relation_with_no_target_warns_and_does_nothing(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window = _open_editor(qtbot)
    _select_only(window, "deck_west")
    window._panel.relation_type_combo.setCurrentIndex(window._panel.relation_type_combo.findData("center_of"))
    window._panel.relation_target_combo.clear()  # no targets available
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    window._on_apply_relation()

    assert len(warnings) == 1
    assert window.session.doc.get("deck_west").relation is None


def test_apply_relation_that_creates_a_cycle_warns_and_rolls_back(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window = _open_editor(qtbot)
    # deck_east already has mirror_of deck_west — pointing deck_west back
    # at deck_east is a real 2-cycle, not a synthetic test case.
    _select_only(window, "deck_west")
    window._panel.relation_type_combo.setCurrentIndex(window._panel.relation_type_combo.findData("mirror_of"))
    window._panel.relation_target_combo.setCurrentIndex(window._panel.relation_target_combo.findText("deck_east"))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    window._on_apply_relation()

    assert len(warnings) == 1
    assert "cycle" in warnings[0][2]
    assert window.session.doc.get("deck_west").relation is None


def test_relation_param_fields_relabel_per_type(qtbot):
    window = _open_editor(qtbot)
    window.show()
    _select_only(window, "deck_west")

    window._panel.relation_type_combo.setCurrentIndex(window._panel.relation_type_combo.findData("mirror_of"))
    assert window._panel.relation_param1_label.text() == "About X"
    assert window._panel.relation_param1_spin.isVisible()
    assert not window._panel.relation_param2_spin.isVisible()

    window._panel.relation_type_combo.setCurrentIndex(window._panel.relation_type_combo.findData("relative_to"))
    assert window._panel.relation_param1_label.text() == "Offset X"
    assert window._panel.relation_param2_label.text() == "Offset Y"
    assert window._panel.relation_param2_spin.isVisible()

    window._panel.relation_type_combo.setCurrentIndex(window._panel.relation_type_combo.findData("center_of"))
    assert not window._panel.relation_param1_spin.isVisible()
    assert window._panel.relation_target_combo.isVisible()  # target field is still needed for center_of


def test_relation_target_excludes_the_selected_object_itself(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "deck_west")
    targets = [window._panel.relation_target_combo.itemText(i) for i in range(window._panel.relation_target_combo.count())]
    assert "deck_west" not in targets
    assert "firepit" in targets


def test_set_relation_is_undoable_via_menu(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "deck_west")
    window._panel.relation_type_combo.setCurrentIndex(window._panel.relation_type_combo.findData("center_of"))
    window._panel.relation_target_combo.setCurrentIndex(window._panel.relation_target_combo.findText("firepit"))
    window._on_apply_relation()
    assert window._undo_action.isEnabled()

    window._on_undo()

    assert window.session.doc.get("deck_west").relation is None


# --- resize/rotate selection handles ---------------------------------------


def test_selecting_a_single_object_shows_two_handles(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    assert len(window._selection_handles) == 2
    assert {h.kind for h in window._selection_handles} == {"resize", "rotate"}


def test_deselecting_removes_handles(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    window._view.scene().clearSelection()
    assert window._selection_handles == []


def _mouse_drag(view: QGraphicsView, start_scene_pos: QPointF, end_scene_pos: QPointF, steps: int = 1) -> None:
    """A *real* click-drag-release, dispatched through Qt's actual mouse
    event pipeline (QTest.mousePress/mouseMove/mouseRelease on the
    view's viewport, in viewport pixel coordinates via `mapFromScene`) —
    not `handle.setPos()` + `handle.end_drag()`, which every existing
    resize/rotate test uses and which completely bypasses
    `QGraphicsItem`'s own default mouse handling. That gap is exactly
    what let a real bug through undetected (see
    `test_real_mouse_drag_on_rotate_handle_does_not_move_the_selected_object`'s
    docstring) — Rich asked for "a legitimate GUI click and rotate test"
    for precisely this reason.

    `steps` > 1 sends several intermediate `mouseMove`s instead of one
    big jump — a real drag, not a teleport. This matters: the
    move-acceleration bug (see
    `test_real_multi_step_mouse_drag_moves_by_exactly_the_mouse_distance`)
    only shows up across a *second* move event, since it's a compounding
    bug — a single-jump drag (`steps=1`, the default, fine for the
    handle tests above) can't reveal it."""
    start = view.mapFromScene(start_scene_pos)
    end = view.mapFromScene(end_scene_pos)
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=start)
    for i in range(1, steps + 1):
        frac = i / steps
        intermediate = start_scene_pos + (end_scene_pos - start_scene_pos) * frac
        QTest.mouseMove(view.viewport(), pos=view.mapFromScene(intermediate))
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)


def test_real_mouse_drag_on_rotate_handle_does_not_move_the_selected_object(qtbot):
    """A real, confirmed bug, found only by driving the rotate handle
    with genuine QTest mouse events instead of `setPos()`: Qt's default
    `QGraphicsItem.mouseMoveEvent`, when the scene has a selection,
    moves that *whole selection* together with whatever movable item
    you're actually dragging — even one, like a handle, that isn't
    itself selected. Since the target object (`shed`) stays selected
    for as long as its handles are shown, dragging the rotate handle
    silently dragged `shed` too, translating it underneath the rotate
    preview and moving its origin — exactly the "origin should not
    change" invariant Rich flagged. Fixed by having `SelectionHandle`
    own its press/move handling instead of relying on the
    `QGraphicsItem` default. Reproduced with real numbers before fixing
    (shed's centroid drifted from (5.5, 4.0) to roughly (8.44, 2.0)) and
    confirmed fixed the same way.

    Checks `transform.tx`/`ty` directly, not `shed.pos()`:
    `EditableItem.itemChange` always vetoes its own Qt-level `pos()`
    back to the old value and tracks movement through
    `scene_object.transform` instead — `pos()` stays (0, 0) either way,
    bug or no bug, which is exactly why it can't be trusted to reveal
    this one."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")
    shed_object = window.session.doc.get("shed")
    tx_before, ty_before = shed_object.transform.tx, shed_object.transform.ty  # "shed" starts at tx=0.5, not 0

    center = rotate_handle._center
    _mouse_drag(window._view, rotate_handle.pos(), QPointF(center.x() + 3, center.y()))

    assert shed_object.transform.tx == tx_before
    assert shed_object.transform.ty == ty_before


def test_real_mouse_drag_rotates_the_object_without_moving_its_origin(qtbot):
    """The end-to-end invariant Rich asked to lock in: rotating via a
    real click-drag on the handle must change the object's rotation
    but leave its origin (centroid) exactly where it was."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")

    rotation_before = window.session.doc.get("shed").transform.rotation
    centroid_before = window.session.resolved.get("shed").geometry.centroid
    before = (centroid_before.x, centroid_before.y)

    center = rotate_handle._center
    _mouse_drag(window._view, rotate_handle.pos(), QPointF(center.x() + 3, center.y()))

    rotation_after = window.session.doc.get("shed").transform.rotation
    centroid_after = window.session.resolved.get("shed").geometry.centroid
    assert rotation_after != pytest.approx(rotation_before, abs=0.5)
    assert centroid_after.x == pytest.approx(before[0], abs=0.01)
    assert centroid_after.y == pytest.approx(before[1], abs=0.01)


def test_real_mouse_drag_on_resize_handle_does_not_move_the_selected_object(qtbot):
    """The same bug, other handle: dragging the resize handle with a
    real mouse gesture must not translate the underlying object. Checks
    `transform.tx`/`ty`, not `shed.pos()` — see the rotate-handle
    version of this test for why `pos()` can't reveal this bug."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")
    shed_object = window.session.doc.get("shed")
    tx_before, ty_before = shed_object.transform.tx, shed_object.transform.ty  # "shed" starts at tx=0.5, not 0

    _mouse_drag(window._view, resize_handle.pos(), resize_handle.pos() + QPointF(0.5, 0.0))

    assert shed_object.transform.tx == tx_before
    assert shed_object.transform.ty == ty_before


def test_real_mouse_drag_scales_the_object_without_moving_its_origin(qtbot):
    """The end-to-end invariant Rich asked to lock in, for scale: a real
    click-drag on the resize handle must change scale but leave the
    object's origin (centroid) exactly where it was."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")

    scale_before = window.session.doc.get("shed").transform.scale
    centroid_before = window.session.resolved.get("shed").geometry.centroid
    before = (centroid_before.x, centroid_before.y)

    _mouse_drag(window._view, resize_handle.pos(), resize_handle.pos() + QPointF(0.5, 0.0))

    scale_after = window.session.doc.get("shed").transform.scale
    centroid_after = window.session.resolved.get("shed").geometry.centroid
    assert scale_after != pytest.approx(scale_before, abs=0.001)
    assert centroid_after.x == pytest.approx(before[0], abs=0.01)
    assert centroid_after.y == pytest.approx(before[1], abs=0.01)


def test_resize_handle_updates_scale_and_syncs_panel(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")

    resize_handle.setPos(resize_handle.pos() * 2)
    resize_handle.end_drag()

    new_scale = window.session.doc.get("shed").transform.scale
    assert new_scale > 1.0
    assert window._panel.scale_spin.value() == pytest.approx(new_scale, abs=0.01)


def test_rotate_handle_updates_rotation_and_syncs_panel(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    before = window.session.doc.get("shed").transform.rotation  # shed starts at 5 degrees, not 0
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")

    center = rotate_handle._center
    rotate_handle.setPos(QPointF(center.x() + 3, center.y()))  # due 'east' of center: a 90-degree move

    rotate_handle.end_drag()

    after = window.session.doc.get("shed").transform.rotation
    # top-to-east is clockwise on screen, i.e. -90 in the scene's
    # counter-clockwise-positive convention (this once asserted +90,
    # encoding the mirrored-commit bug — see
    # test_rotate_preview_turns_the_same_direction_as_the_committed_geometry)
    assert after == pytest.approx(before - 90.0, abs=0.5)
    assert window._panel.rotation_spin.value() == pytest.approx(after, abs=0.5)


def test_resize_gesture_pushes_exactly_one_undo_entry(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")
    depth_before = len(window.session._undo_stack)

    resize_handle.setPos(resize_handle.pos() * 1.2)
    resize_handle.setPos(resize_handle.pos() * 1.3)  # still the same gesture: itemChange keeps firing
    resize_handle.end_drag()

    assert len(window.session._undo_stack) - depth_before == 1


def test_resize_is_undoable(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    before = window.session.doc.get("shed").transform.scale
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")
    resize_handle.setPos(resize_handle.pos() * 2)
    resize_handle.end_drag()

    window._on_undo()

    assert window.session.doc.get("shed").transform.scale == before


def test_rotate_after_move_rotates_in_place_not_around_stale_center(qtbot):
    """A real, confirmed bug, not a hypothetical: SelectionHandle._center
    used to be cached once at handle-construction time. A plain move-drag
    deliberately doesn't rebuild the scene (see EditableItem), so it never
    recreated the handles either — meaning rotating right after moving an
    object (without reselecting in between) rotated it about its
    *pre-move* center, making it visibly swing to a new position instead
    of turning in place. Reproduced with the exact numbers from manual
    diagnosis before fixing it."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")

    shed.setPos(QPointF(10, 10))
    center_after_move = shed.sceneBoundingRect().center()

    rotate_handle.setPos(QPointF(rotate_handle.pos().x() + 3, rotate_handle.pos().y()))

    center_during_rotate = shed.sceneBoundingRect().center()
    assert center_during_rotate.x() == pytest.approx(center_after_move.x(), abs=0.01)
    assert center_during_rotate.y() == pytest.approx(center_after_move.y(), abs=0.01)

    rotate_handle.end_drag()
    center_after_commit = shed.sceneBoundingRect().center()
    assert center_after_commit.x() == pytest.approx(center_after_move.x(), abs=0.01)
    assert center_after_commit.y() == pytest.approx(center_after_move.y(), abs=0.01)


def test_resize_after_move_scales_about_current_center_not_stale(qtbot):
    """The same bug, other handle: resizing after a move must scale about
    the object's post-move center, not wherever it was when the handle
    was first created."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")

    shed.setPos(QPointF(10, 10))
    center_after_move = shed.sceneBoundingRect().center()

    resize_handle.setPos(resize_handle.pos() + QPointF(0.5, 0))
    resize_handle.end_drag()

    center_after_resize = shed.sceneBoundingRect().center()
    assert center_after_resize.x() == pytest.approx(center_after_move.x(), abs=0.01)
    assert center_after_resize.y() == pytest.approx(center_after_move.y(), abs=0.01)


def test_handle_center_refreshes_even_without_an_intervening_move(qtbot):
    """Sanity check: the fix (re-reading _center at the start of every
    gesture) must not break the ordinary case where nothing moved."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")
    expected_center = shed.sceneBoundingRect().center()

    rotate_handle.setPos(QPointF(rotate_handle.pos().x() + 3, rotate_handle.pos().y()))

    assert rotate_handle._center.x() == pytest.approx(expected_center.x(), abs=0.01)
    assert rotate_handle._center.y() == pytest.approx(expected_center.y(), abs=0.01)


def test_resize_cannot_exceed_the_per_gesture_clamp(qtbot):
    """A real bug, not a hypothetical: dragging a resize handle far
    enough used to blow the scale up unboundedly. A single gesture can
    now change scale by at most SelectionHandle.MAX_GESTURE_FACTOR, no
    matter how far the mouse moves."""
    from landscape.editor import SelectionHandle

    window = _open_editor(qtbot)
    _select_only(window, "deck_south")  # a thin, wide object — the shape that triggered this bug
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")

    # a huge drag, far beyond anything a real gesture would produce
    resize_handle.setPos(resize_handle.pos() + QPointF(500, 500))
    resize_handle.end_drag()

    new_scale = window.session.doc.get("deck_south").transform.scale
    assert new_scale == pytest.approx(SelectionHandle.MAX_GESTURE_FACTOR, abs=0.01)


def test_resize_is_less_sensitive_when_zoomed_out(qtbot):
    """The other half of the same bug: the same absolute scene-space drag
    distance must produce a smaller scale change when the view is zoomed
    out, since a zoomed-out view means that same scene distance
    corresponds to a smaller physical mouse movement."""
    window_zoomed_in = _open_editor(qtbot)
    _select_only(window_zoomed_in, "deck_south")
    handle_in = next(h for h in window_zoomed_in._selection_handles if h.kind == "resize")
    drag_offset = QPointF(5, 0)
    handle_in.setPos(handle_in.pos() + drag_offset)
    handle_in.end_drag()
    scale_zoomed_in = window_zoomed_in.session.doc.get("deck_south").transform.scale

    window_zoomed_out = _open_editor(qtbot)
    window_zoomed_out._view.scale(0.1, 0.1)  # zoom out 10x from the same starting point
    _select_only(window_zoomed_out, "deck_south")
    handle_out = next(h for h in window_zoomed_out._selection_handles if h.kind == "resize")
    handle_out.setPos(handle_out.pos() + drag_offset)  # the SAME scene-space drag distance
    handle_out.end_drag()
    scale_zoomed_out = window_zoomed_out.session.doc.get("deck_south").transform.scale

    assert abs(scale_zoomed_out - 1.0) < abs(scale_zoomed_in - 1.0)


def test_handle_pivots_on_shapely_centroid_not_bounding_box_center(qtbot):
    """A real bug, not a hypothetical: SelectionHandle used to pivot its
    live preview on `path().boundingRect().center()`, but the committed
    rotation/scale in geometry.py's `_apply_transform` pivots on
    `origin="centroid"`. For a symmetric shape (a rect, a circle) those
    two points coincide, which is why this went unnoticed — but
    `garden_walkway` is a bent 3-point line, whose bbox center and
    centroid are genuinely different points (confirmed: (9.86, 12.69)
    vs (9.43, 12.91) in scene coordinates). Pivoting on the wrong one
    means the object visibly jumps the instant a rotate/resize commits
    and geometry.py re-resolves it about the *true* centroid instead."""
    window = _open_editor(qtbot)
    _select_only(window, "garden_walkway")
    walkway = next(i for i in window._view.scene().items() if i.data(0) == "garden_walkway")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")

    page_height = window.session.doc.page_height
    true_centroid = window.session.resolved.get("garden_walkway").geometry.centroid
    expected = QPointF(true_centroid.x, page_height - true_centroid.y)
    bbox_center = walkway.path().boundingRect().center()

    # the two points really are different here — otherwise this test
    # would pass even with the old, buggy bbox-center pivot
    assert abs(expected.x() - bbox_center.x()) > 0.1 or abs(expected.y() - bbox_center.y()) > 0.1

    assert rotate_handle._center.x() == pytest.approx(expected.x(), abs=0.01)
    assert rotate_handle._center.y() == pytest.approx(expected.y(), abs=0.01)


def test_rotate_commit_does_not_jump_for_an_asymmetric_shape(qtbot):
    """The end-to-end symptom of the bbox-center-vs-centroid bug: rotate
    an asymmetric object with the handle, commit it, and recompute the
    real geometry. The object's centroid (the point the whole rotation
    pivoted around) must land in the same place before and after commit
    — if the preview pivoted on the wrong point, it would jump here."""
    window = _open_editor(qtbot)
    _select_only(window, "garden_walkway")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")

    centroid_before = window.session.resolved.get("garden_walkway").geometry.centroid
    before = (centroid_before.x, centroid_before.y)

    center = rotate_handle._center
    rotate_handle.setPos(QPointF(center.x() + 3, center.y()))
    rotate_handle.end_drag()  # commits via EditorSession.set_rotation -> recompute()

    centroid_after = window.session.resolved.get("garden_walkway").geometry.centroid
    assert centroid_after.x == pytest.approx(before[0], abs=0.01)
    assert centroid_after.y == pytest.approx(before[1], abs=0.01)


def _pos_at_distance_factor(handle, factor: float) -> QPointF:
    """A position `factor` times as far from the handle's captured center
    as its current position — NOT `handle.pos() * factor`, which moves
    relative to the scene *origin*, not the object's center; the two only
    coincide when the center happens to sit at (0, 0). A real mismatch
    found while testing this: a naive `pos() * 0.5` after the center was
    nowhere near the origin produced a wildly different distance ratio
    than intended, though the underlying resize math was correct all along."""
    center = handle._center
    current = handle.pos()
    return QPointF(center.x() + (current.x() - center.x()) * factor, center.y() + (current.y() - center.y()) * factor)


def test_second_drag_on_same_handle_uses_updated_baseline(qtbot):
    """Dragging the same handle instance twice without an intervening
    rebuild must use the first drag's committed result as its baseline,
    not whatever the handle was constructed with."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")

    resize_handle.setPos(_pos_at_distance_factor(resize_handle, 2.0))
    resize_handle.end_drag()
    scale_after_first = window.session.doc.get("shed").transform.scale
    assert scale_after_first != 1.0  # sanity: the first drag actually did something

    # start of the second gesture: the handle must re-read the committed
    # result of the first gesture as ITS baseline, not the value it was
    # constructed with (1.0)
    resize_handle.setPos(resize_handle.pos() + QPointF(0.01, 0))  # nudge to trigger a fresh itemChange
    assert resize_handle._start_scale == pytest.approx(scale_after_first)
    resize_handle.end_drag()


def test_rebuild_while_handles_are_active_does_not_crash(qtbot):
    """A real risk given this project's history: _rebuild_scene() replaces
    the whole QGraphicsScene, which could destroy a still-referenced
    handle. Anything that triggers an unrelated rebuild while handles
    exist must not crash, and must leave fresh, usable handles behind."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")  # 'shed' is on the 'structures' layer

    window._on_layer_toggled("ground", False)  # a layer 'shed' is NOT on
    window._on_layer_toggled("ground", True)

    assert len(window._selection_handles) == 2
    # the refreshed handles are live, working objects, not stale references
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")
    before = window.session.doc.get("shed").transform.scale
    resize_handle.setPos(_pos_at_distance_factor(resize_handle, 1.5))
    resize_handle.end_drag()
    assert window.session.doc.get("shed").transform.scale != before


def test_handles_positioned_at_target_bounding_box(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    target = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    rect = target.path().boundingRect()

    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")
    assert resize_handle.pos() == rect.topRight()
    assert rotate_handle.pos().y() < rect.top()  # above the object, not on it


# --- watch-and-reload -------------------------------------------------


def _stop_watching(qtbot, window: EditorWindow) -> None:
    """A real finding, not a hypothetical: the OS-level QFileSystemWatcher
    delivers its signal asynchronously, and it can arrive *after* a test
    function returns — once `monkeypatch` has already restored the real
    QMessageBox.question, so a late-delivered signal calls the actual
    modal dialog with no display to show it on, aborting the process.
    Draining pending events while this test's monkeypatch is still active,
    then stopping the watch outright, keeps that signal from ever
    escaping into a later test."""
    qtbot.wait(50)
    window._file_watcher.removePaths(window._file_watcher.files())


def test_load_scene_watches_the_file(qtbot, tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)

    window.load_scene(scene_copy, show_annotations=True)

    assert window._file_watcher.files() == [str(scene_copy)]
    assert window._last_known_mtime_ns == scene_copy.stat().st_mtime_ns


def test_loading_a_second_scene_stops_watching_the_first(qtbot, tmp_path):
    first = tmp_path / "first.yaml"
    first.write_text(EXAMPLE_SCENE.read_text())
    second = tmp_path / "second.yaml"
    second.write_text(EXAMPLE_SCENE.read_text())
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(first, show_annotations=True)

    window.load_scene(second, show_annotations=True)

    assert window._file_watcher.files() == [str(second)]


def test_own_save_does_not_trigger_a_reload_or_dialog(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(scene_copy, show_annotations=True)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a))

    window.save_scene()
    window._on_file_changed_externally(str(scene_copy))

    assert asked == []
    _stop_watching(qtbot, window)


def test_external_change_with_no_unsaved_edits_auto_reloads(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(scene_copy, show_annotations=True)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a))

    scene_copy.write_text(EXAMPLE_SCENE.read_text() + "\n# appended externally\n")
    window._on_file_changed_externally(str(scene_copy))

    assert asked == []
    assert "Reloaded" in window.statusBar().currentMessage()
    _stop_watching(qtbot, window)


def test_external_change_with_unsaved_edits_asks_before_reloading(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(scene_copy, show_annotations=True)
    _select_only(window, "shed")
    window._panel.rotation_spin.setValue(77)  # an unsaved edit
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)

    scene_copy.write_text(EXAMPLE_SCENE.read_text() + "\n# appended externally\n")
    window._on_file_changed_externally(str(scene_copy))

    # chose "No": the edit survives, nothing got reloaded
    assert window.session.doc.get("shed").transform.rotation == 77
    _stop_watching(qtbot, window)


def test_choosing_yes_reloads_and_discards_the_edit(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(scene_copy, show_annotations=True)
    _select_only(window, "shed")
    original_rotation = window.session.doc.get("shed").transform.rotation
    window._panel.rotation_spin.setValue(77)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    scene_copy.write_text(EXAMPLE_SCENE.read_text() + "\n# appended externally\n")
    window._on_file_changed_externally(str(scene_copy))

    assert window.session.doc.get("shed").transform.rotation == original_rotation
    assert not window.session.dirty
    _stop_watching(qtbot, window)


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
    window._panel.material_combo.setCurrentIndex(window._panel.material_combo.findData("water"))

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

    window.load_scene(_scene_copy(EXAMPLE_SCENE), show_annotations=True)

    assert window._hidden_layers == set()


# --- undo/redo ---------------------------------------------------------


def test_undo_action_disabled_until_an_edit_happens(qtbot):
    window = _open_editor(qtbot)
    assert not window._undo_action.isEnabled()

    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)
    window._panel.rotation_spin.setValue(77)

    assert window._undo_action.isEnabled()


def test_undo_action_reverts_panel_edit(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)
    before = window.session.doc.get("shed").transform.rotation
    window._panel.rotation_spin.setValue(77)

    window._on_undo()

    assert window.session.doc.get("shed").transform.rotation == before
    assert window._redo_action.isEnabled()


def test_redo_action_reapplies_undone_edit(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    shed.setSelected(True)
    window._panel.rotation_spin.setValue(77)
    window._on_undo()

    window._on_redo()

    assert window.session.doc.get("shed").transform.rotation == 77


def test_drag_gesture_produces_exactly_one_undo_step(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    depth_before = len(window.session._undo_stack)

    shed.setPos(QPointF(1, 0))
    shed.setPos(QPointF(2, 0))
    shed.setPos(QPointF(3, 0))

    assert len(window.session._undo_stack) - depth_before == 1

    # simulate the release that would normally end the gesture (no real
    # QGraphicsSceneMouseEvent to dispatch here) — the next move should
    # then start a fresh gesture and push a second snapshot
    shed._dragging = False
    shed.setPos(QPointF(4, 0))
    assert len(window.session._undo_stack) - depth_before == 2


def test_click_without_movement_does_not_push_undo(qtbot):
    window = _open_editor(qtbot)
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    depth_before = len(window.session._undo_stack)

    shed.setSelected(True)  # a selection click, no movement

    assert len(window.session._undo_stack) == depth_before


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
    window.load_scene(_scene_copy(BACKYARD_SCENE), show_annotations=True)

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
    window.load_scene(_scene_copy(BACKYARD_SCENE), show_annotations=True)
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


def _fill_vertices(item) -> list[QPointF]:
    """An item's outline as drawn on screen — its path mapped through
    whatever Qt-level preview transform (rotation/scale) it carries."""
    return list(item.mapToScene(item.path().toFillPolygon()))


def _max_vertex_mismatch(a: list[QPointF], b: list[QPointF]) -> float:
    """Worst distance from any vertex in `a` to its nearest vertex in `b`
    — order-agnostic, since the two outlines may start at different
    corners."""
    return max(min(math.hypot(p.x() - q.x(), p.y() - q.y()) for q in b) for p in a)


def test_rotate_preview_turns_the_same_direction_as_the_committed_geometry(qtbot):
    """A real, confirmed bug: the handle's live preview measures its
    angle in Qt's y-down coordinates (positive = clockwise on screen),
    but the committed `transform.rotation` feeds Shapely's
    `affinity.rotate` in the scene's y-up coordinates (positive =
    counter-clockwise). Adding the Qt delta to the stored rotation
    unchanged committed the mirror image of the preview — a 45° drag on
    `shed` (starting at 5°) previewed at ~-40° but committed 50°, so the
    object visibly flipped on the next rebuild. A 90° drag (what the
    older rotate tests use) can't catch this for a rectangle: +90 and
    -90 look nearly identical, which is why it went unnoticed."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")

    center = rotate_handle._center
    # the handle starts straight above the centroid; up-and-right is 45° clockwise on screen
    rotate_handle.setPos(QPointF(center.x() + 3, center.y() - 3))
    preview = _fill_vertices(shed)
    rotate_handle.end_drag()

    window._rebuild_scene()
    rebuilt_shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    assert _max_vertex_mismatch(preview, _fill_vertices(rebuilt_shed)) < 0.05


def _expected_handle_positions(window: EditorWindow, object_id: str) -> tuple[QPointF, QPointF]:
    """Where the resize/rotate handles belong for the object's *committed*
    geometry: resize at the bounding box's top-right corner, rotate just
    above its top edge — computed from `session.resolved` (the document's
    truth), not from any Qt item, so it can't agree with a stale preview."""
    minx, miny, maxx, maxy = window.session.resolved.get(object_id).geometry.bounds
    page_height = window.session.doc.page_height
    top, bottom = page_height - maxy, page_height - miny
    margin = max((bottom - top) * 0.15, 0.5)
    return QPointF(maxx, top), QPointF((minx + maxx) / 2, top - margin)


def _assert_handles_on_object(window: EditorWindow, object_id: str) -> None:
    expected_resize, expected_rotate = _expected_handle_positions(window, object_id)
    handles = {h.kind: h for h in window._selection_handles}
    for kind, expected in (("resize", expected_resize), ("rotate", expected_rotate)):
        pos = handles[kind].pos()
        assert pos.x() == pytest.approx(expected.x(), abs=0.01), kind
        assert pos.y() == pytest.approx(expected.y(), abs=0.01), kind


def test_handles_return_to_the_object_edge_after_a_real_rotate_drag(qtbot):
    """Rich: "scaling or rotating an object causes their handles to move
    off to a location away from the object." The handle used to stay
    wherever the mouse dropped it (and the other handle stayed at the
    pre-rotation bounding box), since a handle commit deliberately
    doesn't rebuild the scene. Both must sit on the rotated object's
    edge once the gesture ends."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")

    center = rotate_handle._center
    _mouse_drag(window._view, rotate_handle.pos(), QPointF(center.x() + 3, center.y() - 3), steps=5)

    _assert_handles_on_object(window, "shed")


def test_handles_return_to_the_object_edge_after_a_real_resize_drag(qtbot):
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    resize_handle = next(h for h in window._selection_handles if h.kind == "resize")

    _mouse_drag(window._view, resize_handle.pos(), _pos_at_distance_factor(resize_handle, 1.5), steps=5)

    assert window.session.doc.get("shed").transform.scale != 1.0  # sanity: it actually resized
    _assert_handles_on_object(window, "shed")


def test_second_rotate_gesture_continues_from_the_first_without_snapping(qtbot):
    """Rotating twice in a row (no reselect, no rebuild in between) must
    not snap the object back at the start of the second gesture — the
    first gesture's preview rotation has to be folded into the item's
    real outline on commit, not left as a Qt transform the second
    gesture then overwrites."""
    window = _open_editor(qtbot)
    _select_only(window, "shed")
    shed = next(i for i in window._view.scene().items() if i.data(0) == "shed")
    rotate_handle = next(h for h in window._selection_handles if h.kind == "rotate")

    center = rotate_handle._center
    _mouse_drag(window._view, rotate_handle.pos(), QPointF(center.x() + 3, center.y() - 3), steps=5)
    after_first = _fill_vertices(shed)

    # a tiny second gesture must barely move the outline
    rotate_handle.setPos(rotate_handle.pos() + QPointF(0.01, 0))
    assert _max_vertex_mismatch(_fill_vertices(shed), after_first) < 0.05
    rotate_handle.end_drag()


# --- selecting dashed annotation / keepout objects -------------------------


def _open_backyard_editor(qtbot) -> EditorWindow:
    """The real design, with annotations shown — `firepit_keepout` and the
    `fence_enclosure` ground-cover box only exist in `backyard.yaml`,
    not the `example.yaml` fixture `_open_editor` loads."""
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(_scene_copy(BACKYARD_SCENE), show_annotations=True)
    return window


def _click_scene_point(window: EditorWindow, x_ft: float, y_ft: float) -> None:
    """A real mouse click at a scene point given in the document's own
    feet (+y north), converted to Qt's y-down scene coordinates and then
    to viewport pixels."""
    page_height = window.session.doc.page_height
    view = window._view
    pixel = view.mapFromScene(QPointF(x_ft, page_height - y_ft))
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=pixel)


@pytest.mark.parametrize(
    "object_id, outline_point",
    [
        # the keepout circle's westernmost point: c=(8.588, 4.965), r=6.0
        ("firepit_keepout", (2.588, 4.965)),
        # the ground-cover box's west edge, midway up — clear of the deck
        # and pad, which both start further east
        ("fence_enclosure", (4.991, 15.977)),
    ],
)
def test_clicking_a_dashed_objects_outline_selects_it(qtbot, object_id, outline_point):
    """Rich: "I am unable to select the firepit keepout," nor the dashed
    box around the deck and hot tub (`fence_enclosure`, marking an
    optional ground cover). Both are drawn by `_add_annotation_item` as
    plain, non-selectable `QGraphicsPathItem`s rather than `EditableItem`s.
    A real click on the dashed outline must select the object."""
    window = _open_backyard_editor(qtbot)

    _click_scene_point(window, *outline_point)

    assert window._selected_id == object_id


def test_clicking_inside_the_ground_cover_box_still_selects_the_hot_tub(qtbot):
    """Guard for whatever fix makes the dashed objects selectable: they're
    unfilled outlines drawn *over* other objects, so their interior must
    not start stealing clicks from what's inside them."""
    window = _open_backyard_editor(qtbot)

    _click_scene_point(window, 11.966, 16.5)  # the hot tub's center: (8.466, 13.0) + 7x7 / 2

    assert window._selected_id == "hot_tub"


def test_dragging_the_keepout_outline_moves_it(qtbot):
    """Selectable isn't much use if it can't then be moved — the keepout's
    position is itself an open design question (recentre it on the
    firepit?), so it has to be draggable like any other object."""
    window = _open_backyard_editor(qtbot)
    page_height = window.session.doc.page_height
    start = QPointF(2.588, page_height - 4.965)  # on the keepout's west edge

    _mouse_drag(window._view, start, start + QPointF(1.0, 0), steps=5)

    t = window.session.doc.get("firepit_keepout").transform
    # clicks land on whole viewport pixels (~0.05 ft each at this zoom), so allow a couple
    assert t.tx == pytest.approx(1.0, abs=0.1)
    assert t.ty == pytest.approx(0.0, abs=0.1)
    assert window.session.doc.get("site_circle").transform.tx == 0  # the object underneath stayed put


# --- Tab cycles through the objects under the mouse pointer ---------------


def _shown_backyard_editor(qtbot) -> EditorWindow:
    """Shown and active, so keyboard focus moves between widgets for real."""
    window = _open_backyard_editor(qtbot)
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is window)
    return window


def _tab_on_canvas(window: EditorWindow, backwards: bool = False) -> None:
    QTest.keyClick(window._view, Qt.Key_Backtab if backwards else Qt.Key_Tab)


def test_tab_on_the_canvas_cycles_through_every_object_under_the_pointer(qtbot):
    """Rich: layered objects are hard to reach by clicking alone, so with
    an object selected on the canvas, Tab steps the selection through
    every object under the mouse pointer, top to bottom, then wraps.
    Under the hot tub's centre: hot_tub (z 3), hot_tub_pad (z 2),
    site_circle (z 1)."""
    window = _shown_backyard_editor(qtbot)
    _click_scene_point(window, 11.966, 16.5)
    assert window._selected_id == "hot_tub"

    visited = []
    for _ in range(3):
        _tab_on_canvas(window)
        visited.append(window._selected_id)

    assert visited == ["hot_tub_pad", "site_circle", "hot_tub"]
    assert window._view.hasFocus()  # Tab stayed on the canvas, not moved to the panel


def test_shift_tab_on_the_canvas_cycles_the_other_way(qtbot):
    window = _shown_backyard_editor(qtbot)
    _click_scene_point(window, 11.966, 16.5)

    _tab_on_canvas(window, backwards=True)

    assert window._selected_id == "site_circle"


def test_tab_uses_the_pointers_current_position_not_the_last_click(qtbot):
    """"Under the mouse pointer" means where the pointer is *now*: select
    something, move the pointer elsewhere without clicking, then Tab."""
    window = _shown_backyard_editor(qtbot)
    _click_scene_point(window, 11.966, 16.5)  # selects hot_tub
    page_height = window.session.doc.page_height
    firepit = window._view.mapFromScene(QPointF(8.812, page_height - 5.725))
    QTest.mouseMove(window._view.viewport(), pos=firepit)

    _tab_on_canvas(window)

    # hot_tub isn't under the pointer any more, so the cycle starts at the top: firepit
    assert window._selected_id == "firepit"
    _tab_on_canvas(window)
    assert window._selected_id == "site_circle"


def test_tab_reaches_a_dashed_outline_and_the_object_beneath_it(qtbot):
    window = _shown_backyard_editor(qtbot)
    _click_scene_point(window, 2.588, 4.965)  # the keepout's west edge
    assert window._selected_id == "firepit_keepout"

    _tab_on_canvas(window)

    assert window._selected_id == "site_circle"


def test_tab_in_the_properties_panel_still_moves_between_controls(qtbot):
    """Only the canvas repurposes Tab: once focus is in the right-hand
    panel, Tab moves between its controls as usual and leaves the
    selection alone."""
    window = _shown_backyard_editor(qtbot)
    _click_scene_point(window, 11.966, 16.5)
    window._panel.rotation_spin.setFocus()
    assert window._panel.rotation_spin.hasFocus()

    QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab)

    assert not window._panel.rotation_spin.hasFocus()
    assert window._panel.isAncestorOf(QApplication.focusWidget())
    assert window._selected_id == "hot_tub"
