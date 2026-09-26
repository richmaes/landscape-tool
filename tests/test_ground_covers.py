"""River rock and turf grass: ground-cover options for the big circle, with
their own texture in every view — stones and mowing stripes on the plan, in
art mode and in 3D."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from landscape.geometry import ResolvedObject, ResolvedScene, resolve_scene  # noqa: E402
from landscape.ground_covers import ground_spec, ground_texture, river_rocks, turf_stripes, turf_tufts  # noqa: E402
from landscape.materials import find_indistinguishable_pairs, load_materials  # noqa: E402
from landscape.rules import load_rules, run_rules  # noqa: E402
from landscape.scene_io import load_scene  # noqa: E402
from landscape.schema import Camera, SceneDocument  # noqa: E402

REPO = Path(__file__).parent.parent
MATERIALS = REPO / "assets" / "materials.yaml"
CIRCLE = Point(10, 10).buffer(6, quad_segs=32)


def _lib():
    return load_materials(MATERIALS)


def _spec(material_id):
    return ground_spec(_lib().materials[material_id], "ft")


def test_the_library_offers_river_rock_and_turf():
    lib = _lib()
    assert lib.materials["river_rock"].name == "River Rock"
    assert lib.materials["turf"].name == "Turf Grass"
    assert _spec("river_rock").kind == "river_rock" and _spec("river_rock").stone_size == pytest.approx(4 / 12)
    assert _spec("turf").kind == "turf" and _spec("turf").stripe_width == 3
    assert ground_spec(lib.materials["gravel"]) is None and ground_spec(lib.materials["lawn"]) is None
    assert find_indistinguishable_pairs(lib, min_distance=0.12) == []


def test_river_rock_covers_the_area_with_varied_stones_that_stay_inside():
    stones = river_rocks(CIRCLE, _spec("river_rock"))
    areas = np.array([s.area for s, _ in stones])
    assert 0.5 < areas.sum() / CIRCLE.area < 0.95  # well covered, with gaps between stones
    assert areas.std() / areas.mean() > 0.25  # stones differ in size
    assert all(CIRCLE.buffer(1e-6).contains(s) for s, _ in stones)
    tones = [t for _, t in stones]
    assert min(tones) < -0.5 and max(tones) > 0.5
    again = river_rocks(CIRCLE, _spec("river_rock"))
    assert [s.wkb for s, _ in stones] == [s.wkb for s, _ in again]  # the same every time


def test_turf_has_alternating_stripes_and_tufts():
    spec = _spec("turf")
    stripes = turf_stripes(CIRCLE, spec)
    assert sum(s.area for s in stripes) / CIRCLE.area == pytest.approx(0.5, abs=0.12)  # every other band
    assert all(s.bounds[2] - s.bounds[0] <= 3 + 1e-9 for s in stripes)
    assert len(turf_tufts(CIRCLE, spec)) > 100


def test_the_3d_textures_tile_seamlessly():
    for material_id in ("river_rock", "turf"):
        pixels, tile = ground_texture(_spec(material_id), _lib().materials[material_id].color)
        assert pixels.shape == (512, 512, 3) and tile > 0
        seam = np.abs(pixels[:, 0].astype(int) - pixels[:, -1].astype(int)).mean()
        inside = np.abs(pixels[:, 100].astype(int) - pixels[:, 101].astype(int)).mean()
        assert seam < inside * 2.5 + 3  # across the wrap it's no rougher than anywhere else


# --- in every view ---------------------------------------------------------------------------


def _circle_scene(material_id):
    doc = SceneDocument(page_width=20, page_height=20, scale=36)
    return doc, ResolvedScene(objects=[ResolvedObject("circle", CIRCLE, material_id, "ground", 0, False)])


def _flat(material_id, tmp_path):
    from PIL import Image

    from landscape.render_flat import render_scene_to_png

    doc, scene = _circle_scene(material_id)
    out = tmp_path / f"{material_id}.png"
    render_scene_to_png(doc, scene, _lib(), out, dpi=144)  # 72 px per ft
    return np.asarray(Image.open(out).convert("RGB"), int)


def test_flat_render_shows_stones_and_stripes(tmp_path):
    rock = _flat("river_rock", tmp_path)[648:792, 648:792].mean(axis=2)  # a 2 ft patch mid-circle
    gravel = _flat("gravel", tmp_path)[648:792, 648:792].mean(axis=2)
    assert rock.std() > 12 and rock.std() > gravel.std() * 2  # stones, not one flat fill
    turf = _flat("turf", tmp_path)
    row = 720
    # stripes are 3 ft wide from x = 0: x = 7.5 ft sits in a dark band (6-9 ft), x = 10.5 ft in a light one
    dark, light = turf[row, int(7.5 * 72)].sum(), turf[row, int(10.5 * 72)].sum()
    assert light - dark > 15


def test_art_render_textures_the_ground_covers():
    from landscape.render_art import render_art_image

    for material_id in ("river_rock", "turf"):
        doc, scene = _circle_scene(material_id)
        img = np.asarray(render_art_image(doc, scene, _lib(), dpi=50), float)  # 500 px square, circle mid-page
        patch = img[200:300, 200:300].mean(axis=2)
        assert patch.std() > 4, material_id


def test_the_design_canvas_draws_stones_and_stripes(qtbot, tmp_path):
    from landscape.editor import EditorWindow

    counts = {}
    for material_id in ("river_rock", "turf", "gravel"):
        path = tmp_path / f"{material_id}.yaml"
        path.write_text(
            "page_width: 20\npage_height: 20\nscale: 36\nobjects:\n"
            f"  - id: circle\n    type: circle\n    cx: 10\n    cy: 10\n    r: 6\n    material: {material_id}\n"
        )
        window = EditorWindow(materials_path=str(MATERIALS))
        qtbot.addWidget(window)
        window.load_scene(path)
        item = next(i for i in window._view.scene().items() if i.data(0) == "circle")
        counts[material_id] = len(item.ground_items)
    assert counts == {"river_rock": 3, "turf": 1, "gravel": 0}  # stones in three tones; one set of stripes


def test_3d_view_textures_the_ground_cover():
    from landscape.render3d import render_3d_image

    camera = Camera("c", x=10, y=2, z=5, look_x=10, look_y=10, look_z=0, fov=60)
    spreads = {}
    for material_id in ("river_rock", "turf", "gravel"):
        doc, scene = _circle_scene(material_id)
        img = np.asarray(render_3d_image(doc, scene, _lib(), camera, 300, 200, surround=False), float)
        spreads[material_id] = img[150:190, 110:190].mean(axis=2).std()  # the circle, just ahead
    assert spreads["river_rock"] > spreads["gravel"] + 5
    assert spreads["turf"] > spreads["gravel"] + 1


# --- the backyard's rules ------------------------------------------------------------------


def test_river_rock_in_the_circle_is_fire_safe_and_turf_is_flagged():
    """Both are ground covers things stand on (no overlap warnings); turf
    grass in the firepit keep-out is flagged, river rock isn't."""
    doc = load_scene(REPO / "scenes" / "backyard.yaml")
    rules = load_rules(REPO / "rules" / "backyard.yaml")
    results = {}
    for material_id in ("river_rock", "turf"):
        doc.get("site_circle").material = material_id
        violations = run_rules(resolve_scene(doc), rules)
        about_circle = [v.rule_id for v in violations if "site_circle" in v.object_ids]
        results[material_id] = about_circle
    assert "no_unintended_overlaps" not in results["river_rock"] + results["turf"]
    assert "no_burnable_in_firepit_keepout" not in results["river_rock"]
    assert "no_burnable_in_firepit_keepout" in results["turf"]
