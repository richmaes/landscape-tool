from pathlib import Path

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
