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
