"""The 3D view renderer (M11): shapes raised to their heights and drawn in
perspective from a look-at camera, with a surrounding fence and sky.
Checked against hand-worked cases with plain coloured boxes."""

import math
import time
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, box

from landscape.geometry import ResolvedObject, ResolvedScene, resolve_scene
from landscape.materials import Material, MaterialLibrary, load_materials
from landscape.render3d import render_3d_image
from landscape.scene_io import load_scene
from landscape.schema import Camera, SceneDocument, Solid

W, H = 400, 300
RED, BLUE, GREEN = "#FF0000", "#0000FF", "#00C000"


def _lib():
    return MaterialLibrary(materials={
        "red": Material(id="red", name="Red", color=RED),
        "blue": Material(id="blue", name="Blue", color=BLUE),
        "green": Material(id="green", name="Green", color=GREEN),
    })


def _obj(id, geom, material, height, base=0.0):
    return ResolvedObject(id, geom, material, "structures", 1, False, None, None, Solid(base, height))


def _render(objects, camera, surround=False, size=(W, H), lib=None):
    doc = SceneDocument(page_width=40, page_height=40, scale=36)
    img = render_3d_image(doc, ResolvedScene(objects=objects), lib or _lib(), camera, width=size[0], height=size[1],
                          surround=surround)
    return np.asarray(img, int)


def _is(colour_px, hex_colour):
    """Mostly this hue, allowing for shading."""
    target = np.array([int(hex_colour[i : i + 2], 16) for i in (1, 3, 5)])
    dominant = int(np.argmax(target))
    return colour_px[dominant] > 60 and all(colour_px[dominant] > colour_px[c] + 40 for c in range(3) if c != dominant)


# camera at (20, 2), eye height 5, looking north at (20, 30, 5): level, heading 0
LEVEL = Camera("c", x=20, y=2, z=5, look_x=20, look_y=30, look_z=5, fov=60)


def test_output_is_the_requested_size():
    img = _render([], LEVEL)
    assert img.shape == (H, W, 3)


def test_a_box_straight_ahead_is_in_the_middle_of_the_view():
    ahead = _obj("ahead", box(18, 15, 22, 17), "red", 10)
    img = _render([ahead], LEVEL)
    assert _is(img[H // 2, W // 2], RED)


def test_a_box_off_to_the_side_lands_where_perspective_says():
    """A post 15 degrees right of the heading, in a 60 degree view, sits at
    x = centre + (W/2) * tan(15) / tan(30) — the pinhole-camera formula."""
    d = 13.0
    angle = math.radians(15)
    cx, cy = 20 + d * math.sin(angle), 2 + d * math.cos(angle)
    post = _obj("post", Point(cx, cy).buffer(0.3, 32), "red", 10)
    img = _render([post], LEVEL)
    expected_x = W / 2 + (W / 2) * math.tan(angle) / math.tan(math.radians(30))
    row = img[H // 2]
    red_columns = [x for x in range(W) if _is(row[x], RED)]
    assert red_columns
    assert np.mean(red_columns) == pytest.approx(expected_x, abs=4)


def test_nearer_objects_hide_farther_ones():
    near = _obj("near", box(19, 10, 21, 11), "blue", 10)
    far = _obj("far", box(15, 25, 25, 26), "red", 10)
    img = _render([far, near], LEVEL)
    assert _is(img[H // 2, W // 2], BLUE)
    assert _is(img[H // 2, W // 2 + 60], RED)  # the far wall shows beside the near post


def test_things_behind_the_camera_are_not_drawn():
    behind = _obj("behind", box(15, -20, 25, -10), "red", 30)
    img = _render([behind], LEVEL)
    assert not any(_is(img[y, x], RED) for y in range(0, H, 10) for x in range(0, W, 10))


def test_height_is_honoured():
    """A 10 ft box and a 2 ft box at the same distance: seen level from
    5 ft up, the tall one rises above the horizon (the image centre row),
    the short one doesn't."""
    tall = _obj("tall", box(14, 15, 17, 16), "red", 10)
    short = _obj("short", box(23, 15, 26, 16), "blue", 2)
    img = _render([tall, short], LEVEL)
    tall_x = W // 2 - int((W / 2) * (4.5 / 13) / math.tan(math.radians(30)))
    short_x = W // 2 + int((W / 2) * (4.5 / 13) / math.tan(math.radians(30)))
    # 20 px above the horizon is ~0.75 ft above the eye at 13 ft away (5.75 ft
    # up); 100 px below is ~3.75 ft below it (1.25 ft up)
    assert _is(img[H // 2 - 20, tall_x], RED)
    assert not _is(img[H // 2 - 20, short_x], BLUE)
    assert _is(img[H // 2 + 100, short_x], BLUE)


def test_a_base_lifts_an_object_off_the_ground():
    """The hot tub stands on its pad: base 3 ft, height 3 ft — its bottom
    is level with the eye... below it, the gap shows the ground."""
    floating = _obj("floating", box(18, 15, 22, 16), "red", 1, base=5)
    img = _render([floating], LEVEL)
    below = img[H // 2 + 25, W // 2]
    assert not _is(below, RED)


def test_holes_stay_open():
    """A ring (the patio with the sand circle cut out) seen from straight
    above: the middle of the hole isn't the ring's colour, the ring is.
    (Looking straight down also checks the renderer picks a sensible 'up' —
    plan-north — when the sky direction is undefined.)"""
    ring = Point(20, 20).buffer(8, 64).difference(Point(20, 20).buffer(4, 64))
    ground = _obj("ring", ring, "red", 0.5)
    down = Camera("c", x=20, y=20, z=40, look_x=20, look_y=20, look_z=0, fov=60)
    img = _render([ground], down)
    assert not _is(img[H // 2, W // 2], RED)
    six_ft_out = int((W / 2) * (6 / 39.5) / math.tan(math.radians(30)))  # mid-ring, seen from 39.5 ft up
    assert _is(img[H // 2, W // 2 + six_ft_out], RED)


def test_sky_above_and_ground_below():
    img = _render([], LEVEL)
    top, bottom = img[5, W // 2], img[H - 5, W // 2]
    assert top[2] > top[0] + 30  # blue sky
    assert bottom[1] >= bottom[2]  # ground, not sky


def test_the_surrounding_fence_closes_the_view():
    """Rich: a vinyl fence all around the yard, sky above it. Looking level
    at the page's north edge, the fence fills the band just above the
    horizon that would otherwise be sky."""
    open_view = _render([], LEVEL, surround=False)
    fenced = _render([], LEVEL, surround=True)
    probe = (H // 2 - 5, W // 2)
    assert fenced[probe].mean() > 200 and abs(int(fenced[probe][0]) - int(fenced[probe][2])) < 25  # near-white vinyl
    assert not np.array_equal(open_view[probe], fenced[probe])


def test_the_same_scene_renders_identically():
    objs = [_obj("a", box(18, 15, 22, 17), "red", 3), _obj("b", box(10, 20, 12, 30), "green", 6)]
    assert np.array_equal(_render(objs, LEVEL, surround=True), _render(objs, LEVEL, surround=True))


def test_the_backyard_renders_fast_enough_to_preview():
    root = Path(__file__).parent
    doc = load_scene(root / "fixtures" / "backyard_original.yaml")
    scene = resolve_scene(doc)
    camera = Camera("c", x=12, y=1, z=5.5, look_x=12, look_y=16, look_z=1.5, fov=60)
    materials = load_materials(root.parent / "assets" / "materials.yaml")
    render_3d_image(doc, scene, materials, camera, width=320, height=200)  # warm-up (first VTK use)
    start = time.perf_counter()
    img = render_3d_image(doc, scene, materials, camera, width=1200, height=800)
    assert time.perf_counter() - start < 2.0
    assert img.size == (1200, 800)


def test_colours_read_true_to_the_material():
    """A design tool's 3D view must show a deck as the deck colour, not a
    shaded-down brown: a flat surface seen from above renders close to its
    material colour, and a wall facing the camera isn't much darker."""
    lib = _lib()
    lib.materials["deck"] = Material(id="deck", name="Deck", color="#E0B27A")
    deck = np.array([0xE0, 0xB2, 0x7A])
    flat = _obj("floor", box(10, 10, 30, 30), "deck", 0)
    down = Camera("c", x=20, y=20, z=30, look_x=20, look_y=20, look_z=0, fov=40)
    img = _render([flat], down, lib=lib)
    assert np.abs(img[H // 2, W // 2] - deck).max() < 30

    wall = _obj("wall", box(10, 20, 30, 21), "deck", 8)
    front = _render([wall], LEVEL, lib=lib)[H // 2, W // 2]
    assert np.abs(front - deck).max() < 60
