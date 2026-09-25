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
