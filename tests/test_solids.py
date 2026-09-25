"""Heights for the 3D view (M11): each object's base (how high its bottom
sits) and height, from the object's own `solid:`, else its material's,
else a fence's own `height`, else flat."""

import pytest

from landscape.editor_session import EditorSession
from landscape.geometry import resolve_scene
from landscape.materials import Material, MaterialLibrary
from landscape.scene_io import load_scene
from landscape.schema import SchemaError, Solid
from landscape.solids import effective_solid

DEFAULT_MATERIALS = "assets/materials.yaml"

SCENE = (
    "page_width: 20\npage_height: 20\nscale: 36\nobjects:\n"
    "  - id: pad\n    type: rect\n    x: 0\n    y: 0\n    width: 9\n    height: 9\n    material: concrete\n"
    "    solid: {base: 0, height: 0.33}\n\n"
    "  - id: tub\n    type: rect\n    x: 1\n    y: 1\n    width: 7\n    height: 7\n    material: water\n\n"
    "  - id: fence\n    type: fence_line\n    points: [[0, 19], [19, 19]]\n    height: 5\n    material: fence\n\n"
    "  - id: lawn\n    type: rect\n    x: 10\n    y: 0\n    width: 5\n    height: 5\n    material: lawn\n"
)


def _write(tmp_path, text=SCENE):
    path = tmp_path / "s.yaml"
    path.write_text(text)
    return path


def _library(**solids):
    lib = MaterialLibrary(materials={})
    for material_id in ("concrete", "water", "fence", "lawn"):
        lib.materials[material_id] = Material(id=material_id, name=material_id, color="#888888",
                                              solid=solids.get(material_id))
    return lib


def test_an_objects_own_solid_is_parsed(tmp_path):
    doc = load_scene(_write(tmp_path))
    assert doc.get("pad").solid == Solid(base=0, height=0.33)
    assert doc.get("tub").solid is None  # absent until set


def test_a_malformed_solid_is_a_schema_error_with_its_line(tmp_path):
    bad = SCENE.replace("solid: {base: 0, height: 0.33}", "solid: {height: tall}")
    with pytest.raises(SchemaError, match="solid") as excinfo:
        load_scene(_write(tmp_path, bad))
    assert excinfo.value.line == 5


def test_a_negative_height_is_rejected(tmp_path):
    bad = SCENE.replace("solid: {base: 0, height: 0.33}", "solid: {base: 0, height: -1}")
    with pytest.raises(SchemaError, match="solid"):
        load_scene(_write(tmp_path, bad))


def test_effective_solid_precedence(tmp_path):
    """Object's own, else the material's, else a fence's own height, else
    flat on the ground."""
    scene = resolve_scene(load_scene(_write(tmp_path)))
    lib = _library(water={"height": 3.0}, fence={"height": 7.0})

    assert effective_solid(scene.get("pad"), lib) == Solid(0, 0.33)  # the object's own
    assert effective_solid(scene.get("tub"), lib) == Solid(0, 3.0)  # its material's
    assert effective_solid(scene.get("fence"), _library()) == Solid(0, 5.0)  # the fence's own height
    assert effective_solid(scene.get("fence"), lib) == Solid(0, 5.0)  # ...which beats the material's default
    assert effective_solid(scene.get("lawn"), lib) == Solid(0, 0.0)  # flat


def test_the_default_library_gives_decks_and_fences_heights():
    from landscape.materials import load_materials

    lib = load_materials(DEFAULT_MATERIALS)
    assert lib.materials["fence"].solid["height"] == 6.0
    assert lib.materials["deck"].solid["height"] > 0
    assert lib.materials["lawn"].solid is None  # ground surfaces stay flat


def test_set_solid_is_saved_undoable_and_tidy(tmp_path):
    path = _write(tmp_path)
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)

    session.set_solid("tub", base=0.33, height=3.0)

    assert session.doc.get("tub").solid == Solid(0.33, 3.0)
    session.save()
    text = path.read_text()
    assert "    solid: {base: 0.33, height: 3}\n" in text  # compact, whole numbers whole
    assert load_scene(path).get("tub").solid == Solid(0.33, 3.0)
    session.undo()
    assert session.doc.get("tub").solid is None


def test_set_solid_changes_one_value_and_keeps_the_other(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_write(tmp_path))
    session.set_solid("pad", height=0.5)
    assert session.doc.get("pad").solid == Solid(0, 0.5)


def test_set_solid_rejects_a_negative_value(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_write(tmp_path))
    with pytest.raises(ValueError):
        session.set_solid("pad", height=-2)


def test_an_untouched_scene_with_solids_saves_byte_identical(tmp_path):
    path = _write(tmp_path)
    original = path.read_bytes()
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)
    session.save()
    assert path.read_bytes() == original


# --- the Height row in the properties panel -------------------------------------------

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_editor import _answer_close_prompts_with_discard, _select_only  # noqa: E402,F401


def _editor(qtbot, tmp_path):
    from landscape.editor import EditorWindow

    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(_write(tmp_path))
    return window


def test_height_row_shows_what_applies_including_inherited(qtbot, tmp_path):
    window = _editor(qtbot, tmp_path)
    _select_only(window, "pad")
    assert (window._panel.solid_height.value(), window._panel.solid_base.value()) == (0.33, 0)
    _select_only(window, "fence")
    assert window._panel.solid_height.value() == 5  # the fence's own height
    _select_only(window, "lawn")
    assert window._panel.solid_height.value() == 0  # flat


def test_typing_a_height_saves_it_on_the_object(qtbot, tmp_path):
    window = _editor(qtbot, tmp_path)
    _select_only(window, "tub")
    window._panel.solid_height.setValue(3)
    window._panel.solid_base.setValue(0.33)
    assert window.session.doc.get("tub").solid == Solid(0.33, 3.0)
    assert window._selected_id == "tub"
    window._on_undo()
    assert window.session.doc.get("tub").solid == Solid(0.0, 3.0)
