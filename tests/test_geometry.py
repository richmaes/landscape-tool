import math

import pytest

from landscape.schema import (
    BooleanOp,
    Circle,
    Ellipse,
    FenceLine,
    Keepout,
    Line,
    Polygon as PolygonPrimitive,
    Rect,
    RegularPolygon,
    SceneDocument,
    SceneObject,
    Transform,
    WavyPath,
    Walkway,
    CenterOf,
    ChordOf,
    MirrorOf,
    RelativeTo,
)
from landscape.geometry import (
    GeometryError,
    _apply_boolean,
    _apply_transform,
    _chord_geometry,
    primitive_to_geometry,
    resolve_scene,
)
from landscape.scene_io import load_scene
from pathlib import Path

EXAMPLE_SCENE = Path(__file__).parent.parent / "scenes" / "example.yaml"


# --- primitives -------------------------------------------------------


def test_circle_area():
    geom = primitive_to_geometry(Circle(cx=0, cy=0, r=5))
    assert geom.area == pytest.approx(math.pi * 25, rel=1e-3)


def test_ellipse_area():
    geom = primitive_to_geometry(Ellipse(cx=0, cy=0, rx=2, ry=3))
    assert geom.area == pytest.approx(math.pi * 2 * 3, rel=1e-3)


def test_rect_area_and_position():
    geom = primitive_to_geometry(Rect(x=1, y=1, width=4, height=2))
    assert geom.area == pytest.approx(8.0)
    assert geom.bounds == pytest.approx((1, 1, 5, 3))


def test_rect_rotation_preserves_area():
    geom = primitive_to_geometry(Rect(x=0, y=0, width=4, height=2, rotation=30))
    assert geom.area == pytest.approx(8.0, rel=1e-3)


def test_rounded_rect_area_less_than_sharp_rect():
    sharp = primitive_to_geometry(Rect(x=0, y=0, width=4, height=4))
    rounded = primitive_to_geometry(Rect(x=0, y=0, width=4, height=4, corner_r=1))
    assert rounded.area < sharp.area
    # corners cut off = 4 squares of side r minus 4 quarter-circles of radius r
    expected_loss = 4 * (1 * 1 - math.pi * 1**2 / 4)
    assert (sharp.area - rounded.area) == pytest.approx(expected_loss, rel=1e-2)


def test_polygon_area():
    geom = primitive_to_geometry(PolygonPrimitive(points=[(0, 0), (10, 0), (10, 5), (0, 5)]))
    assert geom.area == pytest.approx(50.0)


def test_regular_polygon_hexagon_area():
    geom = primitive_to_geometry(RegularPolygon(cx=0, cy=0, sides=6, size=2))
    expected = (3 * math.sqrt(3) / 2) * 2**2
    assert geom.area == pytest.approx(expected, rel=1e-6)


def test_regular_polygon_rejects_too_few_sides():
    with pytest.raises(GeometryError, match="at least 3 sides"):
        primitive_to_geometry(RegularPolygon(cx=0, cy=0, sides=2, size=1))


def test_line_length():
    geom = primitive_to_geometry(Line(x1=0, y1=0, x2=3, y2=4))
    assert geom.length == pytest.approx(5.0)


def test_fence_line_buffers_to_a_thin_strip():
    geom = primitive_to_geometry(FenceLine(points=[(0, 0), (10, 0)], post_size=0.5))
    assert geom.geom_type == "Polygon"
    assert geom.area == pytest.approx(10 * 0.5, rel=1e-2)


def test_walkway_buffers_to_expected_width():
    geom = primitive_to_geometry(Walkway(points=[(0, 0), (10, 0)], width=3))
    assert geom.area == pytest.approx(10 * 3, rel=1e-2)


def test_keepout_resolves_to_its_shape():
    geom = primitive_to_geometry(Keepout(shape=Circle(cx=0, cy=0, r=6), rule="no_burnable"))
    assert geom.area == pytest.approx(math.pi * 36, rel=1e-3)


def test_keepout_without_shape_raises():
    with pytest.raises(GeometryError, match="no shape"):
        primitive_to_geometry(Keepout(shape=None, rule="x"))


def test_wavy_path_open_is_linestring():
    geom = primitive_to_geometry(
        WavyPath(points=[(0, 0), (5, 2), (10, 0)], closed=False, waviness=0.3, seed=1)
    )
    assert geom.geom_type == "LineString"


def test_wavy_path_closed_is_polygon():
    geom = primitive_to_geometry(
        WavyPath(points=[(0, 0), (5, 5), (10, 0), (5, -5)], closed=True, waviness=0.3, seed=1)
    )
    assert geom.geom_type == "Polygon"


def test_wavy_path_is_deterministic_per_seed():
    wp = WavyPath(points=[(0, 0), (5, 2), (10, 0), (15, 3)], closed=False, waviness=0.5, seed=7)
    geom1 = primitive_to_geometry(wp)
    geom2 = primitive_to_geometry(wp)
    assert geom1.equals_exact(geom2, tolerance=0)


def test_wavy_path_different_seeds_differ():
    a = primitive_to_geometry(WavyPath(points=[(0, 0), (5, 2), (10, 0)], waviness=0.5, seed=1))
    b = primitive_to_geometry(WavyPath(points=[(0, 0), (5, 2), (10, 0)], waviness=0.5, seed=2))
    assert not a.equals_exact(b, tolerance=1e-9)


def test_wavy_path_zero_waviness_stays_on_spline():
    straight = primitive_to_geometry(WavyPath(points=[(0, 0), (10, 0)], waviness=0.0, seed=3))
    minx, miny, maxx, maxy = straight.bounds
    assert miny == pytest.approx(0, abs=1e-6)
    assert maxy == pytest.approx(0, abs=1e-6)


# --- relations ----------------------------------------------------------


def test_chord_of_known_circle():
    circle = primitive_to_geometry(Circle(cx=0, cy=0, r=5))
    chord = _chord_geometry(Line(x1=0, y1=0, x2=0, y2=0), circle, offset=3, angle_deg=0)
    assert chord.length == pytest.approx(8.0, abs=0.01)  # 2*sqrt(5^2-3^2)


def test_chord_of_offset_zero_is_diameter():
    circle = primitive_to_geometry(Circle(cx=0, cy=0, r=5))
    chord = _chord_geometry(Line(x1=0, y1=0, x2=0, y2=0), circle, offset=0, angle_deg=0)
    assert chord.length == pytest.approx(10.0, abs=0.01)


def test_boolean_difference_reduces_area():
    base = primitive_to_geometry(Rect(x=0, y=0, width=10, height=10))
    cut = primitive_to_geometry(Circle(cx=5, cy=5, r=3))
    result = _apply_boolean(base, BooleanOp(op="difference", targets=["cut"]), {"cut": cut})
    assert result.area == pytest.approx(100 - cut.area, rel=1e-3)


def test_boolean_union_and_intersection():
    a = primitive_to_geometry(Rect(x=0, y=0, width=10, height=10))
    b = primitive_to_geometry(Rect(x=5, y=5, width=10, height=10))
    union = _apply_boolean(a, BooleanOp(op="union", targets=["b"]), {"b": b})
    intersection = _apply_boolean(a, BooleanOp(op="intersection", targets=["b"]), {"b": b})
    assert union.area == pytest.approx(175.0)
    assert intersection.area == pytest.approx(25.0)


def test_boolean_unresolved_target_raises():
    a = primitive_to_geometry(Rect(x=0, y=0, width=1, height=1))
    with pytest.raises(GeometryError, match="hasn't been resolved"):
        _apply_boolean(a, BooleanOp(op="union", targets=["missing"]), {})


# --- object-level transform ----------------------------------------------


def test_transform_identity_is_noop():
    geom = primitive_to_geometry(Rect(x=0, y=0, width=2, height=2))
    result = _apply_transform(geom, Transform())
    assert result.equals_exact(geom, tolerance=0)


def test_transform_translate():
    geom = primitive_to_geometry(Rect(x=0, y=0, width=2, height=2))
    result = _apply_transform(geom, Transform(tx=5, ty=-3))
    assert result.bounds == pytest.approx((5, -3, 7, -1))


def test_transform_scale_about_centroid_preserves_center():
    geom = primitive_to_geometry(Rect(x=0, y=0, width=2, height=2))
    result = _apply_transform(geom, Transform(scale=2))
    assert result.centroid.coords[0] == pytest.approx(geom.centroid.coords[0])
    assert result.area == pytest.approx(geom.area * 4)


# --- full scene resolution ------------------------------------------------


def test_resolve_example_scene():
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    assert len(scene.objects) == len(doc.objects)
    assert scene.get("firepit_keepout").rule == "no_burnable_material"


def test_center_of_centers_on_target():
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    firepit_center = scene.get("firepit").geometry.centroid
    keepout_center = scene.get("firepit_keepout").geometry.centroid
    assert keepout_center.x == pytest.approx(firepit_center.x, abs=1e-6)
    assert keepout_center.y == pytest.approx(firepit_center.y, abs=1e-6)


def test_mirror_of_reflects_about_axis():
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    west = scene.get("deck_west").geometry.centroid.x
    east = scene.get("deck_east").geometry.centroid.x
    assert (west + east) / 2 == pytest.approx(30, abs=1e-6)  # about_x: 30


def test_resolve_scene_is_deterministic():
    doc = load_scene(EXAMPLE_SCENE)
    scene1 = resolve_scene(doc)
    scene2 = resolve_scene(doc)
    for o1, o2 in zip(scene1.objects, scene2.objects):
        assert o1.geometry.equals_exact(o2.geometry, tolerance=0)


def test_paint_order_sorted_by_z_then_id():
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    order = scene.paint_order()
    zs = [o.z for o in order]
    assert zs == sorted(zs)


def test_bounds_covers_whole_scene():
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    minx, miny, maxx, maxy = scene.bounds()
    assert minx <= 0
    assert maxx >= doc.page_width - 1  # site_circle etc. extend near the page edge


def test_crop_clips_and_drops_outside_objects():
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    cropped = scene.crop(0, 0, 5, 5)
    assert all(o.geometry.bounds[0] >= -1e-9 for o in cropped.objects)
    assert all(o.geometry.bounds[2] <= 5 + 1e-9 for o in cropped.objects)
    assert len(cropped.objects) < len(scene.objects)
