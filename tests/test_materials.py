from pathlib import Path

import pytest

from landscape.materials import (
    FALLBACK_COLOR,
    MaterialError,
    color_distance,
    find_indistinguishable_pairs,
    load_materials,
    render_swatch,
)

DEFAULT_LIBRARY = Path(__file__).parent.parent / "assets" / "materials.yaml"


def test_load_default_library_has_all_starter_materials():
    lib = load_materials(DEFAULT_LIBRARY)
    for expected in (
        "lawn",
        "planting_bed",
        "mulch",
        "gravel",
        "flagstone",
        "concrete",
        "deck",
        "water",
        "stone_wall",
        "fence",
        "tree_canopy",
    ):
        assert expected in lib.materials, f"missing starter material {expected!r}"


def test_default_library_has_no_indistinguishable_pairs():
    lib = load_materials(DEFAULT_LIBRARY)
    close = find_indistinguishable_pairs(lib, min_distance=0.12)
    assert close == [], f"materials too similar: {close}"


def test_resolve_known_material():
    lib = load_materials(DEFAULT_LIBRARY)
    material = lib.resolve("lawn")
    assert material.name == "Lawn"
    assert material.color == "#B7D9A8"


def test_resolve_unknown_material_falls_back():
    lib = load_materials(DEFAULT_LIBRARY)
    material = lib.resolve("not_a_real_material")
    assert material.color == FALLBACK_COLOR


def test_resolve_none_falls_back():
    lib = load_materials(DEFAULT_LIBRARY)
    assert lib.resolve(None).color == FALLBACK_COLOR


def test_material_missing_color_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("materials:\n  lawn:\n    name: Lawn\n")
    with pytest.raises(MaterialError, match="missing a 'color'"):
        load_materials(bad)


def test_render_swatch_is_flat_fill():
    lib = load_materials(DEFAULT_LIBRARY)
    swatch = render_swatch(lib.resolve("water"), size=16)
    assert swatch.size == (16, 16)
    assert swatch.getpixel((0, 0)) == swatch.getpixel((15, 15)) == (154, 198, 214)


def test_color_distance_identical_is_zero():
    assert color_distance("#B7D9A8", "#B7D9A8") == pytest.approx(0.0)


def test_color_distance_rejects_bad_hex():
    with pytest.raises(MaterialError, match="6-digit hex"):
        color_distance("#FFF", "#000000")


def test_find_indistinguishable_pairs_detects_near_duplicates():
    from landscape.materials import Material, MaterialLibrary

    lib = MaterialLibrary(
        materials={
            "a": Material(id="a", name="A", color="#B7D9A8"),
            "b": Material(id="b", name="B", color="#B8DAA9"),  # nearly identical
        }
    )
    close = find_indistinguishable_pairs(lib, min_distance=0.12)
    assert len(close) == 1
    assert close[0][:2] == ("a", "b")
    assert close[0][2] == pytest.approx(color_distance("#B7D9A8", "#B8DAA9"))


def test_decking_comes_in_several_wood_colours_including_a_darker_one():
    """Rich asked for wood colour options for the decking, specifically a
    darker wood. Same hatch texture as the original deck; alternatives in
    one family, like the paver colours."""
    from landscape.materials import _hex_to_rgb

    lib = load_materials(DEFAULT_LIBRARY)
    woods = ["deck", "deck_dark", "deck_cedar", "deck_weathered"]
    for material_id in woods:
        m = lib.materials[material_id]
        assert m.family == "deck"
        assert m.texture == lib.materials["deck"].texture
    assert sum(_hex_to_rgb(lib.materials["deck_dark"].color)) < sum(_hex_to_rgb(lib.materials["deck"].color)) * 0.6
    assert "dark" in lib.materials["deck_dark"].name.lower()
