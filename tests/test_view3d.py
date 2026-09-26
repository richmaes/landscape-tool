"""The 3D view mode in the editor (M11): Design | Art preview | 3D view,
the 3D picture drawn from the chosen camera and kept current as the
camera, the plan or the window changes."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from test_editor import _answer_close_prompts_with_discard, art_calls  # noqa: E402,F401

DEFAULT_MATERIALS = "assets/materials.yaml"
SCENE = (
    "page_width: 20\npage_height: 20\nscale: 36\nlayers: [ground, structures]\nobjects:\n"
    "  - id: tub\n    type: rect\n    x: 8\n    y: 8\n    width: 4\n    height: 4\n    material: water\n"
    "    layer: structures\n    solid: {base: 0, height: 3}\n\n"
    "  - id: lawn\n    type: rect\n    x: 0\n    y: 0\n    width: 20\n    height: 20\n    material: lawn\n    layer: ground\n"
)
CAMERA = (
    "\ncameras:\n"
    "  - id: from_gate\n    x: 10\n    y: 1\n    z: 5.5\n    look_x: 10\n    look_y: 10\n    look_z: 1.5\n    fov: 60\n"
)


@pytest.fixture
def renders(monkeypatch):
    """Record every 3D render the editor asks for (still rendering it)."""
    import landscape.render3d as render3d

    calls = []
    real = render3d.render_3d_image

    def recording(doc, scene, materials, camera, width=1200, height=800, **options):
        calls.append({"camera": camera, "size": (width, height), "ids": {o.id for o in scene.objects}})
        return real(doc, scene, materials, camera, width=width, height=height, **options)

    monkeypatch.setattr(render3d, "render_3d_image", recording)
    return calls


def _editor(qtbot, tmp_path, text=SCENE + CAMERA):
    from landscape.editor import EditorWindow

    path = tmp_path / "s.yaml"
    path.write_text(text)
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.waitExposed(window)
    window.load_scene(path)
    return window


def test_the_toolbar_offers_a_3d_view_alongside_design_and_art(qtbot, tmp_path, renders):
    from PySide6.QtGui import QKeySequence

    window = _editor(qtbot, tmp_path)
    assert window._view3d_action.shortcut() == QKeySequence("Ctrl+3")

    window._view3d_action.trigger()

    assert window._view3d_action.isChecked()
    assert not window._design_action.isChecked() and not window._art_action.isChecked()
    assert window._left_stack.currentWidget() is window._view3d
    assert not window._view3d.pixmap().isNull()
    assert renders[-1]["camera"].id == "from_gate"
    assert "3D view" in window.statusBar().currentMessage()


def test_the_picture_fills_the_view_at_screen_resolution(qtbot, tmp_path, renders):
    window = _editor(qtbot, tmp_path)
    window._view3d_action.trigger()
    dpr = window._view3d.devicePixelRatioF()
    size = window._view3d.size()
    assert renders[-1]["size"] == (round(size.width() * dpr), round(size.height() * dpr))


def test_switching_back_to_design_shows_the_plan(qtbot, tmp_path, renders):
    window = _editor(qtbot, tmp_path)
    window._view3d_action.trigger()
    window._design_action.trigger()
    assert window._left_stack.currentWidget() is window._view
    window._art_action.trigger()
    assert window._left_stack.currentWidget() is window._view  # the art preview lives on the plan canvas


def test_editing_the_camera_redraws_the_3d_view(qtbot, tmp_path, renders):
    window = _editor(qtbot, tmp_path)
    window._view3d_action.trigger()

    window._camera_panel.z_spin.setValue(12)

    assert renders[-1]["camera"].z == 12


def test_an_unchanged_view_is_reused(qtbot, tmp_path, renders):
    window = _editor(qtbot, tmp_path)
    window._view3d_action.trigger()
    window._design_action.trigger()
    window._view3d_action.trigger()
    assert len(renders) == 1


def test_undo_in_the_3d_view_goes_back_to_the_earlier_picture(qtbot, tmp_path, renders):
    """Undo returns the camera to a view already drawn, so that picture is
    shown again — straight from the cache, without re-rendering."""
    window = _editor(qtbot, tmp_path)
    window._view3d_action.trigger()
    first = window._view3d.pixmap().cacheKey()
    window._camera_panel.z_spin.setValue(12)
    assert renders[-1]["camera"].z == 12
    assert window._view3d.pixmap().cacheKey() != first

    window._on_undo()

    assert window._view3d.pixmap().cacheKey() == first
    assert len(renders) == 2
    assert window._left_stack.currentWidget() is window._view3d


def test_hidden_layers_are_left_out(qtbot, tmp_path, renders):
    window = _editor(qtbot, tmp_path)
    window._on_layer_toggled("structures", False)
    window._view3d_action.trigger()
    assert renders[-1]["ids"] == {"lawn"}


def test_resizing_the_window_redraws_at_the_new_size(qtbot, tmp_path, renders):
    window = _editor(qtbot, tmp_path)
    window._view3d_action.trigger()
    before = renders[-1]["size"]
    window.resize(1300, 900)
    qtbot.waitUntil(lambda: renders[-1]["size"] != before, timeout=3000)


def test_with_no_camera_it_says_how_to_add_one(qtbot, tmp_path, renders):
    window = _editor(qtbot, tmp_path, SCENE)
    window._view3d_action.trigger()
    assert renders == []
    assert "camera" in window._view3d.text().lower()
    window._camera_panel.add_button.click()
    assert renders and renders[-1]["camera"].id == "view_1"


def test_the_export_dialog_offers_the_3d_view(qtbot, tmp_path, renders, monkeypatch):
    from PIL import Image

    from test_editor import _trigger_export

    window = _editor(qtbot, tmp_path)
    out = tmp_path / "view.png"

    def configure(dialog):
        dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData("3d"))
        assert dialog.camera_combo.isEnabled() and dialog.camera_combo.currentText() == "from_gate"
        dialog.size_combo.setCurrentIndex(0)

    _trigger_export(window, monkeypatch, out, configure)

    with Image.open(out) as img:
        assert img.size == tuple(window._last_export_options["size"])
