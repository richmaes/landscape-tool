"""Paver layouts: the individual bricks for each pattern, clipped to the
paved area. What must hold for every pattern: the bricks cover the area
with no gaps and no overlaps, and every brick is the paver's real size."""

import math

import pytest
from shapely.geometry import Point, box
from shapely.ops import unary_union

from landscape.pavers import PATTERNS, paver_bricks

L, W = 8 / 12, 4 / 12  # a standard 8 x 4 in paver, in feet

# minimum_rotated_rectangle (used to measure bricks) makes Shapely divide by
# zero internally on axis-aligned edges; the result is right, the warning noise
pytestmark = pytest.mark.filterwarnings("ignore:.*oriented_envelope:RuntimeWarning")


@pytest.mark.parametrize("pattern", ["herringbone_45", "herringbone_90", "running_bond", "basketweave"])
def test_field_patterns_tile_the_area_exactly(pattern):
    area = box(0, 0, 6, 4)
    bricks = paver_bricks(area, pattern, L, W)

    assert unary_union(bricks).symmetric_difference(area).area < 1e-6  # no gaps, nothing outside
    assert sum(b.area for b in bricks) == pytest.approx(area.area, rel=1e-6)  # so no overlaps either


@pytest.mark.parametrize("pattern", ["herringbone_45", "herringbone_90", "running_bond", "basketweave"])
def test_whole_bricks_are_the_real_paver_size(pattern):
    area = box(0, 0, 16, 12)  # patio-sized, so edge cuts are a small share even at 45 degrees
    bricks = paver_bricks(area, pattern, L, W)
    whole = [b for b in bricks if b.area == pytest.approx(L * W, rel=1e-6)]
    assert len(whole) > len(bricks) * 0.8  # most are whole; only the edge ones are cut
    rect = whole[0].minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    sides = sorted(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2))
    assert sides == pytest.approx([W, L], abs=1e-6)


def test_herringbone_45_runs_diagonally_and_90_squarely():
    area = box(0, 0, 6, 4)

    def angles(pattern):
        out = set()
        for b in paver_bricks(area, pattern, L, W):
            if b.area == pytest.approx(L * W, rel=1e-6):
                xs, ys = b.minimum_rotated_rectangle.exterior.coords.xy
                out.add(round(math.degrees(math.atan2(ys[1] - ys[0], xs[1] - xs[0]))) % 90)
        return out

    assert angles("herringbone_45") == {45}
    assert angles("herringbone_90") == {0}


def test_sailor_course_lays_bricks_lengthwise_around_a_ring():
    """The border around the sand circle: one brick wide (4 in), bricks
    following the curve, joints every brick length."""
    ring = Point(0, 0).buffer(12 + W, 256).difference(Point(0, 0).buffer(12, 256))
    bricks = paver_bricks(ring, "sailor", L, W)

    assert unary_union(bricks).symmetric_difference(ring).area < ring.area * 1e-3
    circumference = 2 * math.pi * (12 + W / 2)
    assert len(bricks) == pytest.approx(circumference / L, abs=1)
    assert all(b.area == pytest.approx(L * W, rel=0.05) for b in bricks)


def test_patterns_are_listed_for_the_ui():
    assert set(PATTERNS) == {"herringbone_45", "herringbone_90", "running_bond", "basketweave", "sailor"}


def test_an_unknown_pattern_is_rejected():
    with pytest.raises(ValueError, match="pattern"):
        paver_bricks(box(0, 0, 1, 1), "cobblestone", L, W)


# --- paver materials and the per-object pattern -------------------------------------

from pathlib import Path  # noqa: E402

from landscape.materials import find_indistinguishable_pairs, load_materials  # noqa: E402
from landscape.pavers import paver_spec  # noqa: E402

REPO = Path(__file__).parent.parent
DEFAULT_MATERIALS = REPO / "assets" / "materials.yaml"
PAVER_COLOURS = ["pavers_light_grey", "pavers_red", "pavers_red_blend", "pavers_tan", "pavers_charcoal"]


def test_the_library_offers_paver_colours():
    lib = load_materials(DEFAULT_MATERIALS)
    for material_id in PAVER_COLOURS:
        m = lib.materials[material_id]
        assert m.texture["style"] == "pavers"
        assert m.family == "pavers"


def test_paver_colours_are_alternatives_but_stand_apart_from_other_materials():
    """Two paver colours are never compared (they're alternatives for the
    same surface), but each must stay distinguishable from every other
    material — including the sand and concrete it sits next to."""
    lib = load_materials(DEFAULT_MATERIALS)
    assert find_indistinguishable_pairs(lib, min_distance=0.12) == []


def test_paver_spec_reads_the_recipe_in_scene_units():
    lib = load_materials(DEFAULT_MATERIALS)
    spec = paver_spec(lib.materials["pavers_light_grey"], None, "ft")
    assert spec.pattern == "herringbone_45"
    assert (spec.length, spec.width) == pytest.approx((8 / 12, 4 / 12))
    assert paver_spec(lib.materials["pavers_light_grey"], "basketweave", "ft").pattern == "basketweave"  # object wins
    assert paver_spec(lib.materials["deck"], None, "ft") is None  # not a paver
    assert paver_spec(lib.materials["pavers_red_blend"], None, "ft").variation > paver_spec(
        lib.materials["pavers_red"], None, "ft"
    ).variation  # a blend varies brick to brick more than a single colour


# --- drawing the bricks ------------------------------------------------------------------

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from landscape.geometry import ResolvedObject, ResolvedScene  # noqa: E402
from landscape.render_art import render_art_image  # noqa: E402
from landscape.render_flat import render_scene_to_png  # noqa: E402
from landscape.schema import SceneDocument  # noqa: E402


def _patio(material="pavers_light_grey", pattern="running_bond"):
    doc = SceneDocument(page_width=4, page_height=4, scale=36)
    obj = ResolvedObject("patio", box(0, 0, 4, 4), material, "ground", 0, False, None, pattern)
    return doc, ResolvedScene(objects=[obj]), load_materials(DEFAULT_MATERIALS)


def _row_brightness(arr, y_ft, ppu):
    """Mean brightness of one pixel row at height y (ft, +y north), away
    from the page edges."""
    row = int(round((4 - y_ft) * ppu))
    return arr[row, int(0.5 * ppu) : int(3.5 * ppu)].mean()


def test_flat_render_draws_the_joints(tmp_path):
    """Running bond: every row boundary (a multiple of the 4 in width) is a
    joint, the middle of each row is brick."""
    doc, scene, lib = _patio()
    out = tmp_path / "p.png"
    render_scene_to_png(doc, scene, lib, out, dpi=288)  # 144 px per ft
    arr = np.asarray(Image.open(out).convert("L"), float)
    joint, middle = _row_brightness(arr, 3 * W, 144), _row_brightness(arr, 2.5 * W, 144)
    assert joint < middle - 15


def test_art_render_draws_the_joints():
    doc, scene, lib = _patio()
    arr = np.asarray(render_art_image(doc, scene, lib, dpi=288).convert("L"), float)
    joint, middle = _row_brightness(arr, 3 * W, 144), _row_brightness(arr, 2.5 * W, 144)
    assert joint < middle - 5


def test_art_bricks_vary_in_tone_and_a_blend_varies_most():
    def brick_tones(material):
        doc, scene, lib = _patio(material, "running_bond")
        arr = np.asarray(render_art_image(doc, scene, lib, dpi=144).convert("L"), float)  # 72 px per ft
        # sample the centre of each brick in one row (row middle y = 2.5 W)
        row = int(round((4 - 2.5 * W) * 72))
        centres = [int(round((x + L / 2) * 72)) for x in np.arange(0.5, 3.4, L)]
        return np.array([arr[row - 2 : row + 3, c - 3 : c + 4].mean() for c in centres])

    red, blend = brick_tones("pavers_red"), brick_tones("pavers_red_blend")
    assert red.std() > 0.5  # not one flat wash
    assert blend.std() > red.std() * 1.5


def test_the_design_canvas_shows_the_joints(qtbot, tmp_path):
    from pathlib import Path

    from landscape.editor import EditorWindow
    from landscape.pavers import paver_bricks

    scene = tmp_path / "patio.yaml"
    scene.write_text(
        "page_width: 4\npage_height: 4\nscale: 36\nobjects:\n"
        "  - id: patio\n    type: rect\n    x: 0\n    y: 0\n    width: 4\n    height: 4\n"
        "    material: pavers_light_grey\n    pattern: basketweave\n"
    )
    window = EditorWindow(materials_path=DEFAULT_MATERIALS)
    qtbot.addWidget(window)
    window.load_scene(scene)

    patio = next(i for i in window._view.scene().items() if i.data(0) == "patio")
    joints = patio.joints_item
    assert joints is not None and joints.parentItem() is patio
    expected = len(paver_bricks(box(0, 0, 4, 4), "basketweave", L, W))
    assert joints.path().elementCount() >= expected * 4  # every brick outlined
