"""Art mode (M6): the watercolor-and-pencil renderer. Small synthetic
scenes at low DPI keep these fast; the look itself is judged by eye (see
out/m6-prototypes), these lock in the properties that must hold."""

import numpy as np
import pytest
from PIL import Image
from shapely.geometry import LineString, box

from landscape.geometry import ResolvedObject, ResolvedScene
from landscape.materials import Material, MaterialLibrary
from landscape.render_art import ArtStyle, _hatch_lines, render_art_image
from landscape.schema import SceneDocument

PAPER = np.array([0xF8, 0xF3, 0xE6], float)


def _doc(size: float = 10) -> SceneDocument:
    return SceneDocument(page_width=size, page_height=size, scale=36)


def _obj(id, geom, material=None, z=0, annotation=False, rule=None, layer="default"):
    return ResolvedObject(id=id, geometry=geom, material=material, layer=layer, z=z, annotation=annotation, rule=rule)


def _library() -> MaterialLibrary:
    return MaterialLibrary(
        materials={
            "lawn": Material(id="lawn", name="Lawn", color="#B7D9A8", texture={"style": "none"}),
            "deck": Material(id="deck", name="Deck", color="#E0B27A", texture={"style": "hatch", "direction": 45}),
            "plain_deck": Material(id="plain_deck", name="Deck", color="#E0B27A", texture={"style": "none"}),
        }
    )


def _render(objects, dpi=40, style=None, size=10, **kwargs) -> np.ndarray:
    img = render_art_image(_doc(size), ResolvedScene(objects=objects), _library(), dpi=dpi, style=style, **kwargs)
    return np.asarray(img, float)


def _px(arr: np.ndarray, x_ft: float, y_ft: float, dpi=40, size=10) -> np.ndarray:
    """The pixel at a scene point (+y north), averaged over a 3x3 patch to
    ride out grain."""
    ppu = 36 / 72 * dpi
    col, row = int(x_ft * ppu), int((size - y_ft) * ppu)
    return arr[row - 1 : row + 2, col - 1 : col + 2].reshape(-1, 3).mean(axis=0)


def test_output_size_follows_dpi_and_print_size():
    img = render_art_image(_doc(), ResolvedScene(objects=[]), _library(), dpi=72)
    assert img.size == (360, 360)  # 10 ft at 36 pt/ft = 5 in; 5 in x 72 DPI


def test_same_seed_reproduces_exactly_and_a_new_seed_differs():
    objects = [_obj("lawn", box(1, 1, 9, 9), "lawn"), _obj("deck", box(3, 3, 6, 6), "deck", z=1)]
    a = _render(objects, style=ArtStyle(seed=3))
    b = _render(objects, style=ArtStyle(seed=3))
    c = _render(objects, style=ArtStyle(seed=4))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_a_wash_lands_near_its_materials_own_pastel():
    arr = _render([_obj("lawn", box(1, 1, 9, 9), "lawn")])
    lawn = np.array([0xB7, 0xD9, 0xA8], float)
    inside = _px(arr, 5, 5)
    assert np.abs(inside - lawn).max() < 40  # a watercolor wash, not an exact flat fill
    assert inside[1] > inside[0] and inside[1] > inside[2]  # still reads green
    assert np.abs(_px(arr, 0.3, 0.3) - PAPER).max() < 20  # untouched corner stays paper


def test_an_object_on_top_is_not_muddied_by_the_one_beneath():
    """Multiply-blended washes stack into mud; the renderer lifts the lower
    wash under an upper object, like a painter leaving it unpainted."""
    deck_alone = _render([_obj("deck", box(3, 3, 7, 7), "plain_deck")])
    deck_on_lawn = _render([_obj("lawn", box(1, 1, 9, 9), "lawn"), _obj("deck", box(3, 3, 7, 7), "plain_deck", z=1)])
    assert np.abs(_px(deck_on_lawn, 5, 5) - _px(deck_alone, 5, 5)).max() < 20


def test_an_unassigned_material_is_left_as_paper_not_magenta():
    """In flat mode an unresolved material renders as a loud magenta
    fallback; in a presentation drawing that would ruin the page, so art
    mode leaves it unpainted (pencil outline only)."""
    arr = _render([_obj("lawn", box(1, 1, 9, 9), "lawn"), _obj("firepit", box(4, 4, 6, 6), None, z=1)])
    centre = _px(arr, 5, 5)
    assert np.abs(centre - PAPER).max() < 25
    assert not (centre[0] > 200 and centre[2] > 200 and centre[1] < 100)


def test_hatch_recipe_adds_pencil_lines_a_plain_material_lacks():
    hatched = _render([_obj("d", box(2, 2, 8, 8), "deck")], dpi=72)
    plain = _render([_obj("d", box(2, 2, 8, 8), "plain_deck")], dpi=72)
    ppu = 36
    region = (slice(int(3 * ppu), int(7 * ppu)), slice(int(3 * ppu), int(7 * ppu)))
    # on brightness, not raw RGB — RGB's std is dominated by the gap between channels
    hatched_l, plain_l = hatched[region].mean(axis=2), plain[region].mean(axis=2)
    assert hatched_l.std() > plain_l.std() * 1.25  # deliberately light pencil (ArtStyle.pencil), but clearly there
    assert hatched_l.mean() < plain_l.mean()


def test_hatch_lines_overshoot_the_region_slightly_but_no_further():
    region = box(0, 0, 4, 2)
    lines = _hatch_lines(region, 45, spacing=0.3, overshoot=0.06)
    assert lines
    assert all(region.buffer(0.06 + 1e-6).contains(line) for line in lines)
    assert any(not region.contains(line) for line in lines)  # the overshoot is real


def test_structures_cast_a_soft_shadow_on_what_is_beneath():
    lawn = _obj("lawn", box(0, 0, 10, 10), "lawn")
    shed = _obj("shed", box(4, 4, 6, 6), "plain_deck", z=1, layer="structures")
    with_shadow = _render([lawn, shed])
    without = _render([lawn, shed], style=ArtStyle(shadow_layers=()))
    just_south_east = (6.1, 3.9)  # the shadow falls down-right of the object
    assert _px(with_shadow, *just_south_east).mean() < _px(without, *just_south_east).mean() - 3


def test_annotations_only_appear_when_asked_for():
    marker = _obj("marker", box(2, 2, 8, 8), None, annotation=True)
    hidden = _render([marker], dpi=72)
    shown = _render([marker], dpi=72, show_annotations=True)
    edge_column = hidden[int(3 * 36) : int(7 * 36), int(2 * 36) - 2 : int(2 * 36) + 3]
    assert shown[int(3 * 36) : int(7 * 36), int(2 * 36) - 2 : int(2 * 36) + 3].mean() < edge_column.mean() - 2


def test_pencil_weight_is_adjustable():
    objects = [_obj("d", box(2, 2, 8, 8), "deck")]
    light = _render(objects, dpi=72, style=ArtStyle(pencil=0.2))
    heavy = _render(objects, dpi=72, style=ArtStyle(pencil=1.0))
    assert heavy.mean() < light.mean()


def test_both_wash_styles_render_and_an_unknown_one_is_rejected():
    objects = [_obj("lawn", box(1, 1, 9, 9), "lawn")]
    for wash in ("diffuse", "layered"):
        inside = _px(_render(objects, style=ArtStyle(wash=wash)), 5, 5)
        assert inside[1] > inside[0]
    with pytest.raises(ValueError, match="wash"):
        _render(objects, style=ArtStyle(wash="splatter"))


def test_the_look_is_resolution_independent():
    """Every size is in feet or inches, so a 2x DPI render is the same
    picture with more pixels — not a smaller or sharper-edged version."""
    objects = [_obj("lawn", box(1, 1, 9, 9), "lawn"), _obj("deck", box(3, 3, 6, 6), "deck", z=1)]
    low = _render(objects, dpi=40)
    high = _render(objects, dpi=80)
    high_down = np.asarray(Image.fromarray(high.astype(np.uint8)).resize(low.shape[1::-1], Image.BOX), float)
    assert np.abs(high_down - low).mean() < 6


def test_line_objects_get_a_pencil_stroke():
    fence = _obj("fence", LineString([(1, 5), (9, 5)]), "plain_deck")
    arr = _render([fence], dpi=72)
    on_line = arr[int(5 * 36) - 1 : int(5 * 36) + 2, 100:260].mean()
    off_line = arr[int(3 * 36) - 1 : int(3 * 36) + 2, 100:260].mean()
    assert on_line < off_line - 10
