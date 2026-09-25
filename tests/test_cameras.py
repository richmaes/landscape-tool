"""Cameras for the 3D view (M11): where the viewer stands and the point
they look at, stored in the scene and edited in Design mode."""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402

from landscape.editor_session import EditorSession  # noqa: E402
from landscape.scene_io import load_scene  # noqa: E402
from landscape.schema import Camera, SchemaError  # noqa: E402

from test_editor import _answer_close_prompts_with_discard, _mouse_drag  # noqa: E402,F401

DEFAULT_MATERIALS = "assets/materials.yaml"
SCENE = (
    "page_width: 20\npage_height: 20\nscale: 36\nobjects:\n"
    "  - id: tub\n    type: rect\n    x: 8\n    y: 8\n    width: 4\n    height: 4\n    material: water\n"
)
WITH_CAMERA = SCENE + (
    "\ncameras:\n"
    "  - id: from_gate\n    x: 10\n    y: 1\n    z: 5.5\n    look_x: 10\n    look_y: 10\n    look_z: 1.5\n    fov: 60\n"
)


def _write(tmp_path, text=SCENE):
    path = tmp_path / "s.yaml"
    path.write_text(text)
    return path


# --- the camera itself ------------------------------------------------------------------


def test_heading_and_tilt_follow_from_the_look_at_point():
    """Heading in degrees clockwise from plan-north (like the north arrow),
    tilt negative looking down."""
    north = Camera("c", x=0, y=0, z=5, look_x=0, look_y=10, look_z=5)
    east_down = Camera("c", x=0, y=0, z=5, look_x=10, look_y=0, look_z=-5)
    assert north.heading == pytest.approx(0)
    assert east_down.heading == pytest.approx(90)
    assert east_down.tilt == pytest.approx(-math.degrees(math.atan2(10, 10)))


def test_cameras_parse_from_the_scene(tmp_path):
    doc = load_scene(_write(tmp_path, WITH_CAMERA))
    assert doc.cameras == [Camera("from_gate", 10, 1, 5.5, 10, 10, 1.5, 60)]
    assert load_scene(_write(tmp_path)).cameras == []


def test_malformed_cameras_are_schema_errors(tmp_path):
    for broken, why in [
        (WITH_CAMERA.replace("    fov: 60\n", "    fov: 200\n"), "fov"),
        (WITH_CAMERA.replace("    x: 10\n    y: 1\n", "    x: ten\n    y: 1\n"), "camera"),
        (WITH_CAMERA.replace("    look_x: 10\n    look_y: 10\n    look_z: 1.5\n", "    look_x: 10\n    look_y: 1\n    look_z: 5.5\n"), "look"),
        (WITH_CAMERA + "  - id: from_gate\n    x: 1\n    y: 1\n    z: 5\n    look_x: 2\n    look_y: 2\n    look_z: 1\n", "duplicate"),
    ]:
        with pytest.raises(SchemaError, match=why):
            load_scene(_write(tmp_path, broken))


# --- editing through the session ---------------------------------------------------------


def test_add_camera_defaults_to_standing_at_the_south_edge_looking_at_the_middle(tmp_path):
    path = _write(tmp_path)
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)

    camera_id = session.add_camera()

    cam = session.doc.cameras[0]
    assert cam.id == camera_id == "view_1"
    assert (cam.x, cam.look_x, cam.look_y) == (10, 10, 10)
    assert cam.y < 3 and cam.z == 5.5 and cam.fov == 60
    session.save()
    assert load_scene(path).cameras == session.doc.cameras


def test_set_camera_is_saved_and_undoable(tmp_path):
    path = _write(tmp_path, WITH_CAMERA)
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)

    session.set_camera("from_gate", x=4, look_z=3)

    cam = session.doc.cameras[0]
    assert (cam.x, cam.y, cam.look_z) == (4, 1, 3)
    session.save()
    assert load_scene(path).cameras[0].x == 4
    session.undo()
    assert session.doc.cameras[0].x == 10


def test_set_camera_rejects_impossible_values(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_write(tmp_path, WITH_CAMERA))
    with pytest.raises(ValueError):
        session.set_camera("from_gate", fov=0)
    with pytest.raises(ValueError):
        session.set_camera("from_gate", look_x=10, look_y=1, look_z=5.5)  # looking at itself
    with pytest.raises(ValueError):
        session.set_camera("nope", x=1)


def test_delete_camera_is_undoable(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_write(tmp_path, WITH_CAMERA))
    session.delete_camera("from_gate")
    assert session.doc.cameras == []
    session.undo()
    assert [c.id for c in session.doc.cameras] == ["from_gate"]


def test_a_scene_with_cameras_saves_byte_identical_when_untouched(tmp_path):
    path = _write(tmp_path, WITH_CAMERA)
    original = path.read_bytes()
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)
    session.save()
    assert path.read_bytes() == original


# --- on the design canvas ---------------------------------------------------------------------


def _editor(qtbot, tmp_path, text=WITH_CAMERA):
    from landscape.editor import EditorWindow

    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.resize(1000, 800)
    window.show()
    qtbot.waitExposed(window)
    window.load_scene(_write(tmp_path, text))
    return window


def _drag_scene(window, frm, to):
    from PySide6.QtWidgets import QApplication

    h = window.session.doc.page_height
    _mouse_drag(window._view, QPointF(frm[0], h - frm[1]), QPointF(to[0], h - to[1]), steps=4)
    QApplication.processEvents()


def test_the_canvas_shows_eye_and_look_at_markers_and_a_view_wedge(qtbot, tmp_path):
    window = _editor(qtbot, tmp_path)
    rig = window._camera_rigs["from_gate"]
    h = window.session.doc.page_height
    assert (rig.eye.scene_point().x(), rig.eye.scene_point().y()) == pytest.approx((10, 1))
    assert (rig.look.scene_point().x(), rig.look.scene_point().y()) == pytest.approx((10, 10))
    wedge = rig.wedge.path().boundingRect()
    assert wedge.top() < h - 9  # the wedge reaches out towards the look-at point


def test_dragging_the_eye_moves_the_camera_and_keeps_its_aim(qtbot, tmp_path):
    window = _editor(qtbot, tmp_path)
    _drag_scene(window, (10, 1), (4, 2))
    cam = window.session.doc.cameras[0]
    assert (cam.x, cam.y) == pytest.approx((4, 2), abs=0.1)
    assert (cam.look_x, cam.look_y) == (10, 10)  # still looking at the same point
    assert window.session.dirty


def test_dragging_the_look_at_point_aims_the_camera(qtbot, tmp_path):
    window = _editor(qtbot, tmp_path)
    _drag_scene(window, (10, 10), (15, 16))
    cam = window.session.doc.cameras[0]
    assert (cam.look_x, cam.look_y) == pytest.approx((15, 16), abs=0.1)
    assert (cam.x, cam.y) == (10, 1)
    window._on_undo()
    assert (window.session.doc.cameras[0].look_x, window.session.doc.cameras[0].look_y) == (10, 10)


def test_the_wedge_follows_a_marker_while_it_is_dragged(qtbot, tmp_path):
    """Live feedback: the wedge turns with the look-at marker mid-drag."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window = _editor(qtbot, tmp_path)
    rig = window._camera_rigs["from_gate"]
    h = window.session.doc.page_height
    view = window._view
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=view.mapFromScene(QPointF(10, h - 10)))
    QTest.mouseMove(view.viewport(), pos=view.mapFromScene(QPointF(18, h - 10)))
    assert rig.wedge.path().boundingRect().right() > 15  # swung east before release
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=view.mapFromScene(QPointF(18, h - 10)))


def test_camera_markers_never_drag_the_selected_object(qtbot, tmp_path):
    from test_editor import _select_only

    window = _editor(qtbot, tmp_path)
    _select_only(window, "tub")
    _drag_scene(window, (10, 1), (4, 2))
    t = window.session.doc.get("tub").transform
    assert (t.tx, t.ty) == (0, 0)


def test_camera_panel_edits_values_and_adds_and_deletes(qtbot, tmp_path):
    window = _editor(qtbot, tmp_path, SCENE)
    panel = window._camera_panel
    assert not panel.fields_enabled()  # no camera yet

    panel.add_button.click()
    assert [c.id for c in window.session.doc.cameras] == ["view_1"]
    assert panel.camera_combo.currentText() == "view_1"

    panel.z_spin.setValue(12)
    panel.fov_spin.setValue(40)
    cam = window.session.doc.cameras[0]
    assert (cam.z, cam.fov) == (12, 40)
    assert "view_1" in window._camera_rigs

    panel.delete_button.click()
    assert window.session.doc.cameras == []
    assert window._camera_rigs == {}
