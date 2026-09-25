from pathlib import Path

import pytest
from PIL import Image

from landscape.geometry import ResolvedObject, ResolvedScene, resolve_scene
from landscape.materials import Material, MaterialLibrary, load_materials
from landscape.render_flat import (
    render_scene_to_pdf,
    render_scene_to_png,
    render_scene_to_svg,
    used_materials_in_scene,
)
from landscape.scene_io import load_scene
from shapely.geometry import Point, box

EXAMPLE_SCENE = Path(__file__).parent.parent / "scenes" / "example.yaml"
DEFAULT_MATERIALS = Path(__file__).parent.parent / "assets" / "materials.yaml"


def _obj(id, geom, material=None, z=0, annotation=False, rule=None):
    return ResolvedObject(id=id, geometry=geom, material=material, layer="default", z=z, annotation=annotation, rule=rule)


def _tiny_library():
    return MaterialLibrary(
        materials={
            "red": Material(id="red", name="Red", color="#FF0000", edge={"weight": 0, "color": None}),
            "blue": Material(id="blue", name="Blue", color="#0000FF"),
        }
    )


def _make_doc_and_surface_size(scale=1.0, page=10.0):
    from landscape.schema import SceneDocument

    return SceneDocument(page_width=page, page_height=page, scale=scale)


# --- file format smoke tests ------------------------------------------


def test_render_to_png_creates_correctly_sized_file(tmp_path):
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    materials = load_materials(DEFAULT_MATERIALS)
    out = tmp_path / "scene.png"
    render_scene_to_png(doc, scene, materials, out)
    assert out.exists()
    with Image.open(out) as img:
        assert img.size == (int(doc.page_width * doc.scale), int(doc.page_height * doc.scale))



# --- M7: PNG at a real DPI, with correct physical sizing ----------------------


def test_png_pixel_size_follows_dpi_and_the_drawings_print_size(tmp_path):
    """The drawing's print size is fixed by the scene: `doc.scale` points
    per foot, 72 points per inch — 24 ft at 36 pt/ft is 12 in, the same
    1/2 in = 1 ft scale as the source PDF. At 300 DPI that's 3600 px."""
    doc = load_scene(EXAMPLE_SCENE)
    out = tmp_path / "scene.png"

    render_scene_to_png(doc, resolve_scene(doc), load_materials(DEFAULT_MATERIALS), out, dpi=300)

    inches_w = doc.page_width * doc.scale / 72
    inches_h = doc.page_height * doc.scale / 72
    with Image.open(out) as img:
        assert img.size == (round(inches_w * 300), round(inches_h * 300))


def test_png_records_its_dpi_so_it_prints_at_the_right_size(tmp_path):
    """Pixel count alone doesn't fix a print size — without the PNG's own
    resolution metadata (pHYs), print dialogs and image apps assume 72 or
    96 DPI and print a 300 DPI render several times too large."""
    doc = load_scene(EXAMPLE_SCENE)
    out = tmp_path / "scene.png"

    render_scene_to_png(doc, resolve_scene(doc), load_materials(DEFAULT_MATERIALS), out, dpi=300)

    with Image.open(out) as img:
        dpi_x, dpi_y = img.info["dpi"]
        assert (round(dpi_x), round(dpi_y)) == (300, 300)
        # and together they give the true physical size (PNG stores whole pixels
        # per metre, so 300 DPI reads back as ~299.9994)
        assert img.size[0] / dpi_x == pytest.approx(doc.page_width * doc.scale / 72, rel=1e-4)


def test_png_content_scales_with_dpi_not_just_the_canvas(tmp_path):
    """A 2x2 ft red square at 0..2 ft must cover 2/24 of the width at any
    DPI — the drawing scales with the canvas, it isn't just padded."""
    from landscape.schema import SceneDocument

    doc = SceneDocument(page_width=24, page_height=24, scale=36)
    scene = ResolvedScene(objects=[_obj("sq", box(0, 22, 2, 24), material="red")])  # top-left corner
    out = tmp_path / "sq.png"

    render_scene_to_png(doc, scene, _tiny_library(), out, dpi=144)

    with Image.open(out) as img:
        px_per_ft = 36 / 72 * 144  # 72 px per foot
        inside = img.getpixel((int(px_per_ft * 1.9), int(px_per_ft * 1)))
        outside = img.getpixel((int(px_per_ft * 2.1), int(px_per_ft * 1)))
        assert inside[:3] == (255, 0, 0)
        assert outside[:3] == (255, 255, 255)

def test_render_to_svg_is_valid_svg(tmp_path):
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    materials = load_materials(DEFAULT_MATERIALS)
    out = tmp_path / "scene.svg"
    render_scene_to_svg(doc, scene, materials, out)
    content = out.read_text()
    assert "<svg" in content
    assert out.stat().st_size > 1000



def test_svg_declares_its_print_size_in_points(tmp_path):
    """A unitless `width="864"` means 864 CSS pixels (96 per inch) in SVG,
    so the drawing printed/imported at 9 in instead of its true 12 in — a
    real bug, found checking M7's "SVG export" item. Sized in points, it
    matches the PDF and the PNG's recorded DPI: `doc.scale` pt per foot."""
    import xml.etree.ElementTree as ET

    doc = load_scene(EXAMPLE_SCENE)
    out = tmp_path / "scene.svg"
    render_scene_to_svg(doc, resolve_scene(doc), load_materials(DEFAULT_MATERIALS), out)

    root = ET.parse(out).getroot()
    assert root.get("width") == f"{doc.page_width * doc.scale:g}pt"
    assert root.get("height") == f"{doc.page_height * doc.scale:g}pt"


def test_svg_is_vector_only(tmp_path):
    """No embedded raster data. (cairo does emit empty, zero-size
    `<image>` placeholders as mask sources — those carry no pixels.)"""
    doc = load_scene(EXAMPLE_SCENE)
    out = tmp_path / "scene.svg"
    render_scene_to_svg(doc, resolve_scene(doc), load_materials(DEFAULT_MATERIALS), out, show_legend=True)

    content = out.read_text()
    assert "data:image" not in content
    assert "<path" in content

def test_render_to_pdf_is_valid_pdf(tmp_path):
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    materials = load_materials(DEFAULT_MATERIALS)
    out = tmp_path / "scene.pdf"
    render_scene_to_pdf(doc, scene, materials, out)
    assert out.read_bytes()[:4] == b"%PDF"


# --- pixel-level correctness ------------------------------------------


def test_fill_matches_material_color(tmp_path):
    doc = _make_doc_and_surface_size(scale=10, page=10)
    scene = ResolvedScene(objects=[_obj("a", box(2, 2, 8, 8), material="red")])
    out = tmp_path / "one.png"
    render_scene_to_png(doc, scene, _tiny_library(), out)
    with Image.open(out) as img:
        rgb = img.convert("RGB")
        # sample well inside the shape, away from any edge stroke
        assert rgb.getpixel((50, 50)) == (255, 0, 0)


def test_unresolved_material_falls_back_to_magenta(tmp_path):
    doc = _make_doc_and_surface_size(scale=10, page=10)
    scene = ResolvedScene(objects=[_obj("a", box(2, 2, 8, 8), material="not_a_real_material")])
    out = tmp_path / "one.png"
    render_scene_to_png(doc, scene, _tiny_library(), out)
    with Image.open(out) as img:
        assert img.convert("RGB").getpixel((50, 50)) == (255, 0, 255)


def test_annotation_object_is_not_filled(tmp_path):
    doc = _make_doc_and_surface_size(scale=10, page=10)
    scene = ResolvedScene(
        objects=[_obj("marker", box(2, 2, 8, 8), material="red", annotation=True)]
    )
    out = tmp_path / "one.png"
    render_scene_to_png(doc, scene, _tiny_library(), out, show_annotations=True)
    with Image.open(out) as img:
        # centroid should still be background white, not filled red
        assert img.convert("RGB").getpixel((50, 50)) == (255, 255, 255)


def test_annotation_excluded_by_default(tmp_path):
    doc = _make_doc_and_surface_size(scale=10, page=10)
    scene = ResolvedScene(
        objects=[_obj("marker", box(2, 2, 8, 8), material="red", annotation=True)]
    )
    out = tmp_path / "one.png"
    render_scene_to_png(doc, scene, _tiny_library(), out, show_annotations=False)
    with Image.open(out) as img:
        rgb = img.convert("RGB")
        # nothing drawn at all: pure white everywhere, including the outline position
        assert rgb.getpixel((20, 50)) == (255, 255, 255)


def test_keepout_zone_is_not_filled(tmp_path):
    doc = _make_doc_and_surface_size(scale=10, page=10)
    scene = ResolvedScene(
        objects=[_obj("zone", box(2, 2, 8, 8), material=None, rule="no_burnable_material")]
    )
    out = tmp_path / "one.png"
    render_scene_to_png(doc, scene, _tiny_library(), out)
    with Image.open(out) as img:
        assert img.convert("RGB").getpixel((50, 50)) == (255, 255, 255)


def test_paint_order_later_z_draws_over_earlier(tmp_path):
    doc = _make_doc_and_surface_size(scale=10, page=10)
    scene = ResolvedScene(
        objects=[
            _obj("bottom", box(1, 1, 9, 9), material="red", z=0),
            _obj("top", box(3, 3, 7, 7), material="blue", z=1),
        ]
    )
    out = tmp_path / "one.png"
    render_scene_to_png(doc, scene, _tiny_library(), out)
    with Image.open(out) as img:
        rgb = img.convert("RGB")
        assert rgb.getpixel((50, 50)) == (0, 0, 255)  # inside 'top'
        assert rgb.getpixel((20, 50)) == (255, 0, 0)  # only 'bottom' covers this


# --- used_materials_in_scene --------------------------------------------


def test_used_materials_excludes_annotations_keepouts_and_fallback():
    scene = ResolvedScene(
        objects=[
            _obj("a", box(0, 0, 1, 1), material="red"),
            _obj("b", box(0, 0, 1, 1), material="blue"),
            _obj("marker", box(0, 0, 1, 1), material="red", annotation=True),
            _obj("zone", box(0, 0, 1, 1), rule="no_burnable_material"),
            _obj("ghost", box(0, 0, 1, 1), material="does_not_exist"),
        ]
    )
    used = used_materials_in_scene(scene, _tiny_library())
    assert [m.id for m in used] == ["blue", "red"]  # sorted by name


# --- M7: scale bar and north arrow ----------------------------------------------


BACKYARD_ORIGINAL = Path(__file__).parent / "fixtures" / "backyard_original.yaml"


def _backyard():
    doc = load_scene(BACKYARD_ORIGINAL)
    return doc, resolve_scene(doc), load_materials(DEFAULT_MATERIALS)


def test_nice_scale_bar_length_is_a_round_number_near_a_quarter_of_the_width():
    from landscape.render_flat import nice_scale_bar_length

    assert nice_scale_bar_length(24) == 5
    assert nice_scale_bar_length(40) == 10
    assert nice_scale_bar_length(100) == 25
    assert nice_scale_bar_length(3) == 0.5


def test_print_scale_label_states_the_real_ratio():
    """36 pt per ft at 72 pt per inch is 1/2 in = 1 ft, i.e. 1:24."""
    from landscape.render_flat import print_scale_label

    assert print_scale_label(36, "ft") == '1/2 in = 1 ft (1:24)'
    assert print_scale_label(18, "ft") == '1/4 in = 1 ft (1:48)'
    assert print_scale_label(72, "ft") == '1 in = 1 ft (1:12)'


def test_decorations_add_a_strip_below_the_drawing_not_over_it(tmp_path):
    """The drawing fills its page edge to edge, so the scale bar and north
    arrow go in a strip *below* it: the page grows taller, its width and
    the drawing itself (still at exact print scale) are unchanged."""
    import pdfplumber

    from landscape.render_flat import DECORATION_STRIP_PT

    doc, scene, materials = _backyard()
    plain, decorated = tmp_path / "plain.pdf", tmp_path / "decorated.pdf"
    render_scene_to_pdf(doc, scene, materials, plain)
    render_scene_to_pdf(doc, scene, materials, decorated, scale_bar=True, north_arrow=True)

    with pdfplumber.open(plain) as p, pdfplumber.open(decorated) as d:
        assert (p.pages[0].width, p.pages[0].height) == (864, 864)
        assert (d.pages[0].width, d.pages[0].height) == (864, 864 + DECORATION_STRIP_PT)


def test_pdf_scale_bar_and_north_arrow_carry_their_labels(tmp_path):
    import pdfplumber

    doc, scene, materials = _backyard()
    out = tmp_path / "plan.pdf"
    render_scene_to_pdf(doc, scene, materials, out, scale_bar=True, north_arrow=True)

    with pdfplumber.open(out) as pdf:
        text = pdf.pages[0].extract_text()
    assert "5 ft" in text
    assert "1:24" in text
    assert "N" in text.split()


def test_scale_bar_is_physically_the_length_it_claims(tmp_path):
    """At 72 DPI one pixel is one point, and the backyard is 36 pt per ft,
    so the 5 ft bar must span 180 px — the whole point of a scale bar."""
    from landscape.render_flat import DECORATION_STRIP_PT, scale_bar_geometry

    doc, scene, materials = _backyard()
    out = tmp_path / "plan.png"
    render_scene_to_png(doc, scene, materials, out, dpi=72, scale_bar=True)

    x0, y, length = scale_bar_geometry(doc)  # scene units (ft), y measured down from the drawing's top
    row = round(y * doc.scale + 1)  # just inside the bar's filled segments
    with Image.open(out) as img:
        assert img.size[1] == 864 + DECORATION_STRIP_PT
        dark = [x for x in range(img.size[0]) if sum(img.getpixel((x, row))[:3]) < 200]
    assert length == 5
    assert min(dark) == pytest.approx(x0 * doc.scale, abs=2)
    assert max(dark) - min(dark) == pytest.approx(length * doc.scale, abs=2)


def test_north_arrow_points_page_up_by_default_and_rotates_with_north_angle():
    """Whether page-up really is north is still an open question (see
    extraction/objects.md), so the angle is a parameter: degrees clockwise
    from page-up."""
    from landscape.render_flat import north_arrow_tip

    cx, cy, size = 10.0, 10.0, 1.0  # cairo page coords: +y is *down*
    assert north_arrow_tip(cx, cy, size, 0) == pytest.approx((10.0, 9.0))
    assert north_arrow_tip(cx, cy, size, 90) == pytest.approx((11.0, 10.0))  # north is page-right



def test_the_drawing_never_spills_into_the_strip(tmp_path):
    """The original design's keep-out overhangs the page bottom by ~1 ft,
    and the site circle's outline touches it; with a strip below, both
    used to draw straight across the scale bar area."""
    doc, scene, materials = _backyard()
    out = tmp_path / "plan.png"
    render_scene_to_png(doc, scene, materials, out, dpi=72, north_arrow=True)  # no scale bar: strip is empty on the left

    with Image.open(out) as img:
        strip_row = 864 + 10  # 10 pt below the drawing's edge
        left_half = [img.getpixel((x, strip_row))[:3] for x in range(img.size[0] // 2)]
    assert all(pixel == (255, 255, 255) for pixel in left_half)


# --- the drawing's own legend box and scale indicator (flat) ---------------------------


def test_flat_legend_is_drawn_at_its_saved_position_with_uniform_swatches(tmp_path):
    from landscape.overlays import legend_entries, legend_layout
    from landscape.schema import Placement, SceneDocument

    doc = SceneDocument(page_width=10, page_height=10, scale=36)
    doc.legend = Placement(5.0, 8.0)
    lib = _tiny_library()
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 2, 2), material="red"), _obj("b", box(3, 0, 4, 1), material="blue")])
    out = tmp_path / "l.png"
    render_scene_to_png(doc, scene, lib, out, dpi=144, show_legend=True)

    layout = legend_layout(doc, legend_entries(scene, lib))
    assert {r.swatch for r in layout.rows} == {layout.rows[0].swatch}
    ppu = 72
    with Image.open(out) as img:
        for row, colour in zip(layout.rows, [(0, 0, 255), (255, 0, 0)]):  # Blue, Red: sorted by name
            cx, cy = row.swatch_x + row.swatch / 2, row.swatch_y - row.swatch / 2
            assert img.getpixel((int(cx * ppu), int((10 - cy) * ppu)))[:3] == colour


def test_flat_scale_indicator_is_drawn_when_asked(tmp_path):
    from landscape.overlays import scale_indicator_layout
    from landscape.schema import SceneDocument

    doc = SceneDocument(page_width=10, page_height=10, scale=36)
    scene = ResolvedScene(objects=[])
    with_bar, without = tmp_path / "a.png", tmp_path / "b.png"
    render_scene_to_png(doc, scene, _tiny_library(), with_bar, dpi=144, scale_indicator=True)
    render_scene_to_png(doc, scene, _tiny_library(), without, dpi=144)

    bar = scale_indicator_layout(doc)
    row, col = int((10 - bar.y) * 72), int((bar.x + bar.length / 2) * 72)
    with Image.open(with_bar) as a, Image.open(without) as b:
        assert sum(a.getpixel((col, row))[:3]) < 200
        assert b.getpixel((col, row))[:3] == (255, 255, 255)
