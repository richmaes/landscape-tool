"""Fence colours and textures: white vinyl slats and cedar boards, with
posts every 8 ft — on the plan (posts), and in the 3D view (a slatted or
boarded panel between taller posts)."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import LineString, box  # noqa: E402

from landscape.fences import fence_centerline, fence_posts, fence_spec  # noqa: E402
from landscape.geometry import ResolvedObject, ResolvedScene, resolve_scene  # noqa: E402
from landscape.materials import find_indistinguishable_pairs, load_materials  # noqa: E402
from landscape.scene_io import load_scene  # noqa: E402
from landscape.schema import Camera, SceneDocument, Solid  # noqa: E402

REPO = Path(__file__).parent.parent
MATERIALS = REPO / "assets" / "materials.yaml"


def _lib():
    return load_materials(MATERIALS)


def test_the_library_offers_vinyl_and_cedar_fences():
    lib = _lib()
    vinyl, cedar = lib.materials["fence_vinyl"], lib.materials["fence_cedar"]
    assert vinyl.family == cedar.family == lib.materials["fence"].family == "fence"
    assert vinyl.solid["height"] == cedar.solid["height"] == 6
    assert find_indistinguishable_pairs(lib, min_distance=0.12) == []  # colours stand apart from everything else


def test_fence_specs_have_slats_and_posts_every_8_ft():
    lib = _lib()
    vinyl = fence_spec(lib.materials["fence_vinyl"], "ft")
    cedar = fence_spec(lib.materials["fence_cedar"], "ft")
    assert vinyl.boards == "vinyl" and cedar.boards == "cedar"
    assert vinyl.post_spacing == cedar.post_spacing == 8
    assert 0.3 < vinyl.slat_width < 0.7 and vinyl.post_size > vinyl.slat_width * 0.5
    assert fence_spec(lib.materials["deck"], "ft") is None  # not a fence


@pytest.mark.parametrize("length, expected", [
    (24, [0, 8, 16, 24]),
    (20, [0, 8, 16, 20]),  # the last bay is shorter, as built
    (5, [0, 5]),
])
def test_posts_every_8_ft_from_the_start_with_one_at_the_end(length, expected):
    posts = fence_posts(LineString([(0, 0), (length, 0)]), spacing=8, size=0.4)
    assert [round(p.centroid.x, 6) for p in posts] == expected
    assert all(p.area == pytest.approx(0.16) for p in posts)


def test_centerline_runs_down_the_middle_of_a_fence_shape():
    """A fence drawn as a thin rect (the back fence) or a buffered line
    (fence_line): the centre line along its long side."""
    line = fence_centerline(box(2, 10, 22, 10.6))
    (x0, y0), (x1, y1) = sorted(line.coords)
    assert (x0, x1) == pytest.approx((2, 22)) and y0 == pytest.approx(10.3) and y1 == pytest.approx(10.3)
    buffered = LineString([(0, 5), (0, 17)]).buffer(0.165, cap_style="flat")
    (x0, y0), (x1, y1) = sorted(fence_centerline(buffered).coords, key=lambda p: p[1])
    assert (x0, y0, y1) == pytest.approx((0, 5, 17), abs=1e-6)


# --- on the plan ------------------------------------------------------------------------


def _fence_doc(material="fence_vinyl"):
    doc = SceneDocument(page_width=30, page_height=10, scale=36)
    fence = ResolvedObject("fence", LineString([(2, 5), (26, 5)]).buffer(0.2, cap_style="flat"), material,
                           "structures", 1, False, None, None, Solid(0, 6))
    return doc, ResolvedScene(objects=[fence])


def test_flat_render_shows_the_posts(tmp_path):
    from PIL import Image

    from landscape.render_flat import render_scene_to_png

    doc, scene = _fence_doc()
    out = tmp_path / "f.png"
    render_scene_to_png(doc, scene, _lib(), out, dpi=144)  # 72 px per ft
    arr = np.asarray(Image.open(out).convert("L"), float)
    row = int((10 - 5) * 72)
    at_post, between = arr[row - 2 : row + 3, int(10 * 72)].mean(), arr[row - 2 : row + 3, int(14 * 72)].mean()
    assert at_post < between - 20  # the post at 8 ft from the start (x = 10) is drawn darker


def test_the_design_canvas_shows_the_posts(qtbot, tmp_path):
    from landscape.editor import EditorWindow

    path = tmp_path / "s.yaml"
    path.write_text(
        "page_width: 30\npage_height: 10\nscale: 36\nobjects:\n"
        "  - id: fence\n    type: fence_line\n    points: [[2, 5], [26, 5]]\n    material: fence_vinyl\n"
    )
    window = EditorWindow(materials_path=str(MATERIALS))
    qtbot.addWidget(window)
    window.load_scene(path)
    fence = next(i for i in window._view.scene().items() if i.data(0) == "fence")
    assert fence.posts_item is not None
    assert fence.posts_item.path().elementCount() >= 4 * 5  # 4 posts (0, 8, 16, 24 ft), each a closed square


# --- in the 3D view -----------------------------------------------------------------------


def _is_sky(px) -> bool:
    """The sky is a gradient (lighter near the horizon), so test for 'clearly
    blue' rather than one exact colour; white vinyl and cedar aren't."""
    return px[2] - px[0] > 30


def _render(material, camera, width=400, height=300):
    from landscape.render3d import render_3d_image

    doc, scene = _fence_doc(material)
    return np.asarray(render_3d_image(doc, scene, _lib(), camera, width, height, surround=False), int)


# standing 10 ft south of the fence, looking straight at it, eye at 4 ft
FACING = Camera("c", x=14, y=-5, z=4, look_x=14, look_y=5, look_z=4, fov=80)


def test_3d_posts_stand_above_the_panel():
    """Posts are a little taller than the slats, so just above the panel's
    top there's a post at x = 10, 18 ft (8 ft apart) and sky in between."""
    img = _render("fence_vinyl", FACING)
    f = (400 / 2) / np.tan(np.radians(40))  # px per unit at distance 1

    def column(x):
        return int(400 / 2 + f * (x - 14) / 10)

    row = int(300 / 2 - f * (6.12 - 4) / 10)  # just above the 6 ft panel top, below the post caps
    assert not _is_sky(img[row, column(10)])  # a post
    assert _is_sky(img[row, column(14)])  # between posts: sky


def test_3d_vinyl_panel_shows_slats_and_cedar_is_wood_coloured():
    vinyl = _render("fence_vinyl", FACING)
    cedar = _render("fence_cedar", FACING)
    band = vinyl[150:170, 150:190].mean(axis=2)  # a stretch of panel between posts
    assert band.max() - band.min() > 12  # slat seams, not one flat colour
    assert band.mean() > 170  # white vinyl
    c = cedar[160, 170]
    assert c[0] > c[1] > c[2] and c.mean() < 170  # warm brown


def test_the_surrounding_fence_is_vinyl_with_posts():
    """The 3D background fence (Rich: vinyl all around the yard) uses the
    vinyl fence's slats and posts, not a plain slab."""
    from landscape.render3d import render_3d_image

    doc = SceneDocument(page_width=40, page_height=40, scale=36)
    camera = Camera("c", x=20, y=30, z=4, look_x=20, look_y=41, look_z=4, fov=80)  # 10 ft from the north fence
    img = np.asarray(render_3d_image(doc, ResolvedScene(objects=[]), _lib(), camera, 400, 300, surround=True), int)
    f = 200 / np.tan(np.radians(40))
    row = int(150 - f * (6.12 - 4) / 10)
    post_columns = [int(200 + f * (x - 20) / 10) for x in (16, 24)]  # posts at x = 0, 8, 16, 24, 32, 40
    assert not any(_is_sky(img[row, c]) for c in post_columns)
    assert _is_sky(img[row, 200])  # x = 20: between posts
