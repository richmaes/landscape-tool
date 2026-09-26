"""3D models from a local folder (never committed): found by name, placed
in the scene as a `model` object, fitted to its declared real-world size
in the 3D view — or drawn as a plain placeholder box when the file isn't
there, so a scene still works on a machine without the model."""

import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

# PyVista is imported inside the helpers, never at the top of a test file: a
# real bug — importing it at collection time, before Qt starts, let VTK set
# up macOS's windowing first; Qt and VTK then fought over it, the whole
# suite ran twice as slowly and the process hung for minutes at exit.

from landscape.geometry import resolve_scene  # noqa: E402
from landscape.materials import load_materials  # noqa: E402
from landscape.models import (  # noqa: E402
    MODEL_EXTENSIONS,
    available_models,
    default_models_dir,
    find_model,
    missing_models,
)
from landscape.scene_io import load_scene  # noqa: E402
from landscape.schema import SchemaError, Solid  # noqa: E402
from landscape.solids import effective_solid  # noqa: E402

REPO = Path(__file__).parent.parent
MATERIALS = REPO / "assets" / "materials.yaml"


def _tall_obj(path: Path) -> Path:
    """A 2 x 6 x 1 box standing up along Y — how most modelling tools
    (and glTF) orient 'up'."""
    import pyvista as pv

    path.parent.mkdir(parents=True, exist_ok=True)
    pv.Box(bounds=(-1, 1, 0, 6, -0.5, 0.5)).save(str(path))
    return path


def _scene(tmp_path, file="bench.obj", size="width: 4\n    depth: 2\n    height: 12", extra=""):
    text = (
        "page_width: 20\npage_height: 20\nscale: 36\nobjects:\n"
        f"  - id: bench\n    type: model\n    file: {file}\n    x: 10\n    y: 10\n    {size}\n{extra}"
    )
    path = tmp_path / "s.yaml"
    path.write_text(text)
    return path


# --- the models folder -------------------------------------------------------------------


def test_the_models_folder_is_never_committed_except_its_readme():
    readme = REPO / "models" / "README.md"
    assert readme.exists()
    probe = REPO / "models" / "probe.glb"
    ignored = subprocess.run(["git", "check-ignore", "-q", str(probe)], cwd=REPO).returncode == 0
    readme_ignored = subprocess.run(["git", "check-ignore", "-q", str(readme)], cwd=REPO).returncode == 0
    assert ignored and not readme_ignored


def test_default_models_dir_is_the_repo_models_folder_unless_overridden(monkeypatch, tmp_path):
    monkeypatch.delenv("LANDSCAPE_MODELS", raising=False)
    assert default_models_dir() == REPO / "models"
    monkeypatch.setenv("LANDSCAPE_MODELS", str(tmp_path))
    assert default_models_dir() == tmp_path


def test_available_models_lists_supported_files_including_subfolders(tmp_path):
    _tall_obj(tmp_path / "bench.obj")
    _tall_obj(tmp_path / "furniture" / "chair.obj")
    (tmp_path / "notes.txt").write_text("not a model")
    (tmp_path / "hot-tub.fbx").write_text("unsupported format")
    assert available_models(tmp_path) == ["bench.obj", "furniture/chair.obj"]
    assert ".glb" in MODEL_EXTENSIONS and ".fbx" not in MODEL_EXTENSIONS


def test_find_model_by_path_or_by_file_name_anywhere_in_the_folder(tmp_path):
    chair = _tall_obj(tmp_path / "furniture" / "chair.obj")
    assert find_model("furniture/chair.obj", tmp_path) == chair
    assert find_model("chair.obj", tmp_path) == chair  # moved into a subfolder: still found
    assert find_model("sofa.obj", tmp_path) is None
    assert find_model("chair.obj", tmp_path / "nowhere") is None  # no folder at all


def test_missing_models_names_what_a_scene_needs_but_the_folder_lacks(tmp_path):
    models = tmp_path / "models"
    _tall_obj(models / "bench.obj")
    doc = load_scene(_scene(tmp_path, extra=(
        "  - id: tub\n    type: model\n    file: hot-tub.glb\n    x: 5\n    y: 5\n    width: 7\n    depth: 7\n    height: 3\n"
    )))
    assert missing_models(doc, models) == ["hot-tub.glb"]


# --- the model object ------------------------------------------------------------------------


def test_a_model_object_parses_and_its_footprint_is_its_width_and_depth(tmp_path):
    doc = load_scene(_scene(tmp_path, size="width: 4\n    depth: 2\n    height: 12\n    rotation: 90"))
    model = doc.get("bench").primitive
    assert (model.file, model.width, model.depth, model.height, model.rotation) == ("bench.obj", 4, 2, 12, 90)
    footprint = resolve_scene(doc).get("bench").geometry
    assert footprint.bounds == pytest.approx((9, 8, 11, 12))  # 4 x 2 turned 90 degrees, centred on (10, 10)


def test_a_models_height_is_its_3d_height(tmp_path):
    scene = resolve_scene(load_scene(_scene(tmp_path)))
    assert effective_solid(scene.get("bench"), load_materials(MATERIALS)) == Solid(0, 12)


@pytest.mark.parametrize("bad, why", [
    ("width: 0\n    depth: 2\n    height: 3", "width"),
    ("width: 2\n    depth: 2", "height"),
])
def test_a_model_needs_a_positive_size(tmp_path, bad, why):
    with pytest.raises(SchemaError, match=why):
        load_scene(_scene(tmp_path, size=bad))


def test_a_model_without_a_file_is_an_error(tmp_path):
    with pytest.raises(SchemaError, match="file"):
        load_scene(_scene(tmp_path, file="''"))


# --- in the 3D view ---------------------------------------------------------------------------


def _placed(tmp_path, models_dir, size="width: 4\n    depth: 2\n    height: 12", file="bench.obj"):
    import pyvista as pv

    from landscape.render3d import place_models

    doc = load_scene(_scene(tmp_path, file=file, size=size))
    scene = resolve_scene(doc)
    plotter = pv.Plotter(off_screen=True)
    try:
        return place_models(plotter, scene, load_materials(MATERIALS), models_dir)
    finally:
        plotter.close()


def test_a_found_model_is_stood_upright_and_fitted_to_its_declared_size(tmp_path):
    """A Y-up 2 x 6 x 1 model declared 4 wide, 2 deep, 12 tall: turned so its
    'up' is the scene's up, scaled x2 to fill that box exactly, centred on
    (10, 10) with its bottom on the ground."""
    models = tmp_path / "models"
    _tall_obj(models / "bench.obj")
    [(object_id, kind, bounds)] = _placed(tmp_path, models)
    assert (object_id, kind) == ("bench", "model")
    assert bounds == pytest.approx((8, 12, 9, 11, 0, 12), abs=1e-6)


def test_a_model_keeps_its_proportions_rather_than_stretching(tmp_path):
    """Declared 4 x 2 x 6 but the model is 2 x 1 x 6 in shape: it's scaled
    to fit inside the declared box (x1 here), never distorted to fill it."""
    models = tmp_path / "models"
    _tall_obj(models / "bench.obj")
    [(_, _, bounds)] = _placed(tmp_path, models, size="width: 4\n    depth: 2\n    height: 6")
    assert bounds == pytest.approx((9, 11, 9.5, 10.5, 0, 6), abs=1e-6)


def test_a_missing_model_becomes_a_placeholder_box_of_its_declared_size(tmp_path):
    [(object_id, kind, bounds)] = _placed(tmp_path, tmp_path / "empty")
    assert (object_id, kind) == ("bench", "placeholder")
    assert bounds == pytest.approx((8, 12, 9, 11, 0, 12), abs=1e-6)


def test_the_3d_view_draws_the_placeholder(tmp_path):
    from landscape.render3d import render_3d_image
    from landscape.schema import Camera

    doc = load_scene(_scene(tmp_path))
    scene = resolve_scene(doc)
    camera = Camera("c", x=10, y=1, z=5, look_x=10, look_y=10, look_z=5, fov=60)
    with_model = np.asarray(render_3d_image(doc, scene, load_materials(MATERIALS), camera, 200, 150,
                                            surround=False, models_dir=tmp_path / "empty"), int)
    doc.objects.clear()
    doc.resolution_order.clear()
    empty = np.asarray(render_3d_image(doc, resolve_scene(doc), load_materials(MATERIALS), camera, 200, 150,
                                       surround=False, models_dir=tmp_path / "empty"), int)
    assert np.abs(with_model[75, 100] - empty[75, 100]).max() > 20  # something stands there


# --- placing one in the editor -------------------------------------------------------------------


def test_create_model_places_it_centred_with_the_models_proportions(tmp_path):
    """Units in model files vary (cm, m, inches), so a new model is sized by
    its proportions — 4 ft across — for the designer to set its real size."""
    from landscape.editor_session import EditorSession

    models = tmp_path / "models"
    _tall_obj(models / "bench.obj")
    path = tmp_path / "s.yaml"
    path.write_text("page_width: 20\npage_height: 20\nscale: 36\nobjects: []\n")
    session = EditorSession(str(MATERIALS))
    session.load(path)

    object_id = session.create_model("bench.obj", models)

    model = session.doc.get(object_id).primitive
    assert (model.file, model.x, model.y) == ("bench.obj", 10, 10)
    assert model.width == pytest.approx(4) and model.depth == pytest.approx(2) and model.height == pytest.approx(12)
    session.save()
    assert load_scene(path).get(object_id).primitive.file == "bench.obj"
    session.undo()
    assert not session.doc.objects


def test_the_editor_marks_a_missing_model_on_the_plan(qtbot, tmp_path):
    from landscape.editor import EditorWindow

    window = EditorWindow(materials_path=str(MATERIALS), models_dir=tmp_path / "empty")
    qtbot.addWidget(window)
    window.load_scene(_scene(tmp_path))
    item = next(i for i in window._view.scene().items() if i.data(0) == "bench")
    labels = [c.text() for c in item.childItems() if hasattr(c, "text")]
    assert any("missing" in label for label in labels)
    assert "bench.obj" in window.statusBar().currentMessage()


def test_create_model_from_the_menu(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from landscape.editor import EditorWindow

    models = tmp_path / "models"
    _tall_obj(models / "bench.obj")
    path = tmp_path / "s.yaml"
    path.write_text("page_width: 20\npage_height: 20\nscale: 36\nobjects: []\n")
    window = EditorWindow(materials_path=str(MATERIALS), models_dir=models)
    qtbot.addWidget(window)
    window.load_scene(path)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("bench.obj", True))

    window._on_create_model()

    assert [o.primitive.file for o in window.session.doc.objects] == ["bench.obj"]
    assert window._selected_id == window.session.doc.objects[0].id


def test_an_obj_models_textures_are_used_and_tile(tmp_path):
    """A real bug: the generated hot tub's plank texture came out plain
    brown. Its long sides tile the texture (coordinates beyond 0..1), which
    VTK clamps to the edge colour unless the texture is set to repeat —
    common in real model files too. The loader now turns repeat on."""
    from PIL import Image

    from landscape.render3d import render_3d_image
    from landscape.schema import Camera

    models = tmp_path / "models"
    models.mkdir()
    stripes = np.zeros((64, 64, 3), np.uint8)
    stripes[:, ::8] = 255  # white stripes on black
    Image.fromarray(stripes).save(models / "stripes.png")
    (models / "wall.mtl").write_text("newmtl striped\nKd 1 1 1\nmap_Kd stripes.png\n")
    (models / "wall.obj").write_text(
        "mtllib wall.mtl\n"
        "v -1 0 0\nv 1 0 0\nv 1 2 0\nv -1 2 0\n"  # a 2 x 2 wall standing up (Y-up), facing +z
        "vt 0 0\nvt 4 0\nvt 4 1\nvt 0 1\n"  # the stripes tile four times across
        "usemtl striped\nf 1/1 2/2 3/3 4/4\n"
    )
    doc = load_scene(_scene(tmp_path, file="wall.obj", size="width: 6\n    depth: 0.1\n    height: 6"))
    camera = Camera("c", x=10, y=1, z=3, look_x=10, look_y=10, look_z=3, fov=40)
    img = np.asarray(render_3d_image(doc, resolve_scene(doc), load_materials(MATERIALS), camera, 300, 200,
                                     surround=False, models_dir=models), float).mean(axis=2)
    band = img[80:120, 150:260]  # the right-hand part of the wall: texture coordinates past 1
    assert band.max() - band.min() > 80  # still stripes, not the clamped edge colour


def test_the_generated_hot_tub_loads_with_its_wood_texture(tmp_path):
    """tools/make_hot_tub_model.py: a 7 x 7 x 3 ft tub, wood outside
    (textured), off-white inside. Every face must carry texture
    coordinates — VTK's OBJ importer drops them for the whole file if any
    face lacks them, which once left the planks plain brown."""
    import importlib.util

    import pyvista as pv

    from landscape.models import model_proportions
    from landscape.render3d import _import_model

    spec = importlib.util.spec_from_file_location("make_hot_tub_model", REPO / "tools" / "make_hot_tub_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    obj = module.make_hot_tub(tmp_path / "tub")

    assert model_proportions(obj, across=7) == pytest.approx((7, 7, 3), abs=0.01)
    plotter = pv.Plotter(off_screen=True)
    try:
        actors = _import_model(plotter, obj)
        textured = [a for a in actors if a.GetTexture() is not None]
        assert textured, "the wood exterior should carry its plank texture"
        assert all(a.GetMapper().GetInput().GetPointData().GetTCoords() is not None for a in textured)
    finally:
        plotter.close()


def test_the_generated_fire_bowl_loads_with_its_concrete_and_glowing_fire(tmp_path):
    """tools/make_fire_bowl_model.py: a 3.5 ft concrete fire bowl with lava
    rocks and flames. The concrete keeps its texture (texture coordinates
    on every face), and the flames glow — their ambient colour is their own
    bright colour, so they aren't shaded dark on the side away from the sun."""
    import importlib.util

    import pyvista as pv

    from landscape.models import model_proportions
    from landscape.render3d import _import_model

    spec = importlib.util.spec_from_file_location("make_fire_bowl_model", REPO / "tools" / "make_fire_bowl_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    obj = module.make_fire_bowl(tmp_path / "bowl")

    width, depth, height = model_proportions(obj, across=3.5)
    assert (width, depth) == pytest.approx((3.5, 3.5), abs=0.01)
    assert height > 1.33 + 0.5  # the bowl is 16 in; the flames rise well above it
    plotter = pv.Plotter(off_screen=True)
    try:
        actors = _import_model(plotter, obj)
        textured = [a for a in actors if a.GetTexture() is not None]
        assert textured and all(a.GetMapper().GetInput().GetPointData().GetTCoords() is not None for a in textured)
        glowing = [a for a in actors if min(a.GetProperty().GetAmbientColor()[:2]) > 0.4]  # bright red and green: fire
        assert len(glowing) >= 3  # the three flame bands
    finally:
        plotter.close()


# --- a 3D model as an option on any design element (the firepit) ---------------------------


def _firepit_scene(tmp_path, model_line="    model: fire_bowl.obj\n"):
    path = tmp_path / "s.yaml"
    path.write_text(
        "page_width: 20\npage_height: 20\nscale: 36\nobjects:\n"
        "  - id: firepit\n    type: ellipse\n    cx: 10\n    cy: 10\n    rx: 1.0\n    ry: 0.95\n"
        f"{model_line}    layer: structures\n    z: 1\n"
    )
    return path


def _bowl(models_dir):
    """A small stand-in 'fire bowl': 2 wide, 2 deep, 1 tall once upright."""
    import pyvista as pv

    models_dir.mkdir(parents=True, exist_ok=True)
    pv.Box(bounds=(-1, 1, 0, 1, -1, 1)).save(str(models_dir / "fire_bowl.obj"))


def test_any_object_can_name_a_3d_model_and_keeps_its_own_shape(tmp_path):
    doc = load_scene(_firepit_scene(tmp_path))
    assert doc.get("firepit").model == "fire_bowl.obj"
    firepit = resolve_scene(doc).get("firepit")
    assert firepit.geometry.geom_type == "Polygon"  # still its ellipse on the plan
    assert firepit.model.file == "fire_bowl.obj"
    assert (firepit.model.x, firepit.model.y) == pytest.approx((10, 10))
    assert (firepit.model.width, firepit.model.depth) == pytest.approx((2.0, 1.9), abs=0.02)
    assert load_scene(_firepit_scene(tmp_path, "")).get("firepit").model is None


def test_the_model_is_fitted_to_the_elements_footprint_keeping_proportions(tmp_path):
    """No height given: the model keeps its own proportions, scaled to fit
    the footprint (2.0 x 1.9 ft here, so x0.95)."""
    from landscape.render3d import place_models

    import pyvista as pv

    models = tmp_path / "models"
    _bowl(models)
    doc = load_scene(_firepit_scene(tmp_path))
    plotter = pv.Plotter(off_screen=True)
    try:
        [(object_id, kind, bounds)] = place_models(plotter, resolve_scene(doc), load_materials(MATERIALS), models)
    finally:
        plotter.close()
    assert (object_id, kind) == ("firepit", "model")
    assert bounds == pytest.approx((9.05, 10.95, 9.05, 10.95, 0, 0.95), abs=0.02)


def test_a_missing_elements_model_draws_a_placeholder(tmp_path):
    from landscape.render3d import place_models

    import pyvista as pv

    doc = load_scene(_firepit_scene(tmp_path))
    plotter = pv.Plotter(off_screen=True)
    try:
        [(_, kind, bounds)] = place_models(plotter, resolve_scene(doc), load_materials(MATERIALS), tmp_path / "none")
    finally:
        plotter.close()
    assert kind == "placeholder" and bounds[5] > 0.3  # a visible stand-in, not a flat outline


def test_choosing_a_model_is_saved_undoable_and_removable(tmp_path):
    from landscape.editor_session import EditorSession

    path = _firepit_scene(tmp_path, "")
    session = EditorSession(str(MATERIALS))
    session.load(path)

    session.set_object_model("firepit", "Fire Bowl/fire_bowl.obj")
    session.save()
    assert "    model: Fire Bowl/fire_bowl.obj\n" in path.read_text()
    session.set_object_model("firepit", None)
    session.save()
    assert "model:" not in path.read_text()
    session.undo()
    assert session.doc.get("firepit").model == "Fire Bowl/fire_bowl.obj"


def test_the_panel_offers_the_folders_models_for_the_selected_element(qtbot, tmp_path):
    from landscape.editor import EditorWindow
    from test_editor import _select_only

    models = tmp_path / "models"
    _bowl(models / "Fire Bowl")
    window = EditorWindow(materials_path=str(MATERIALS), models_dir=models)
    qtbot.addWidget(window)
    window.load_scene(_firepit_scene(tmp_path, ""))
    _select_only(window, "firepit")
    combo = window._panel.model_combo
    assert [combo.itemData(i) for i in range(combo.count())] == [None, "Fire Bowl/fire_bowl.obj"]
    assert combo.currentData() is None

    combo.setCurrentIndex(combo.findData("Fire Bowl/fire_bowl.obj"))

    assert window.session.doc.get("firepit").model == "Fire Bowl/fire_bowl.obj"
    assert window._selected_id == "firepit"
    assert window._panel.model_combo.currentData() == "Fire Bowl/fire_bowl.obj"


def test_an_elements_model_turns_with_the_element(tmp_path):
    path = _firepit_scene(tmp_path, "    model: fire_bowl.obj\n    transform: {rotation: 30}\n")
    placement = resolve_scene(load_scene(path)).get("firepit").model
    assert placement.rotation == 30
    assert (placement.width, placement.depth) == pytest.approx((2.0, 1.9), abs=0.02)  # its own size, not the turned box's
