"""The drawing's legend box and scale indicator: their contents, layout,
default placement, and saved (movable) positions in the scene document."""

import shutil
import tempfile
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from landscape.editor_session import EditorSession
from landscape.geometry import ResolvedObject, ResolvedScene
from landscape.materials import Material, MaterialLibrary
from landscape.overlays import legend_entries, legend_layout, scale_indicator_layout
from landscape.scene_io import load_scene
from landscape.schema import Placement, SceneDocument, SchemaError

REPO = Path(__file__).parent.parent
BACKYARD = Path(__file__).parent / "fixtures" / "backyard_original.yaml"
DEFAULT_MATERIALS = REPO / "assets" / "materials.yaml"


def _obj(id, geom, material=None, layer="default", annotation=False, rule=None):
    return ResolvedObject(id=id, geometry=geom, material=material, layer=layer, z=0, annotation=annotation, rule=rule)


def _library():
    return MaterialLibrary(
        materials={
            "deck": Material(id="deck", name="Deck", color="#E0B27A"),
            "water": Material(id="water", name="Water", color="#9AC6D6"),
        }
    )


def test_legend_lists_materials_as_squares_then_unassigned_items_as_circles():
    scene = ResolvedScene(
        objects=[
            _obj("deck_a", box(0, 0, 1, 1), "deck"),
            _obj("deck_b", box(2, 0, 3, 1), "deck"),  # same material: one row
            _obj("tub", box(0, 2, 1, 3), "water"),
            _obj("firepit", Point(5, 5).buffer(1), None),
            _obj("water_feature_a", box(6, 6, 7, 7), None),
            _obj("water_feature_b", box(8, 8, 9, 9), None),  # grouped with _a
            _obj("marker", box(0, 0, 9, 9), None, annotation=True),  # never listed
            _obj("keepout", Point(5, 5).buffer(3), None, rule="no_burn"),  # never listed
        ]
    )

    entries = legend_entries(scene, _library())

    assert [(e.shape, e.label) for e in entries] == [
        ("square", "Deck"),
        ("square", "Water"),
        ("circle", "Firepit"),
        ("circle", "Water feature"),
    ]
    assert entries[0].color == "#E0B27A"
    assert entries[2].color is None  # no material chosen yet


def test_legend_leaves_out_hidden_layers():
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 1, 1), "deck", layer="structures"), _obj("b", box(0, 0, 1, 1), "water")])
    labels = [e.label for e in legend_entries(scene, _library(), hidden_layers={"structures"})]
    assert labels == ["Water"]


def test_legend_rows_are_uniform_and_sized_on_paper_not_in_feet():
    """Same swatch size and row height for every entry, and the same size
    on paper whatever the scene's scale (so a 1:48 plan's legend isn't half
    the size of a 1:24 one's)."""
    scene = ResolvedScene(objects=[_obj("a", box(0, 0, 1, 1), "deck"), _obj("f", Point(0, 0).buffer(1), None)])
    entries = legend_entries(scene, _library())
    at_24 = legend_layout(SceneDocument(page_width=24, page_height=24, scale=36), entries)
    at_48 = legend_layout(SceneDocument(page_width=48, page_height=48, scale=18), entries)

    assert len({round(r.swatch, 6) for r in at_24.rows}) == 1
    assert len({round(b.swatch_y - a.swatch_y, 6) for a, b in zip(at_24.rows, at_24.rows[1:])}) == 1
    assert at_48.rows[0].swatch == pytest.approx(at_24.rows[0].swatch * 2)  # twice the feet = same inches


def test_default_positions_are_bottom_left_and_bottom_right_on_the_page():
    doc = SceneDocument(page_width=24, page_height=24, scale=36)
    legend = legend_layout(doc, legend_entries(ResolvedScene(objects=[_obj("a", box(0, 0, 1, 1), "deck")]), _library()))
    scale = scale_indicator_layout(doc)

    assert legend.x < 2 and legend.y - legend.height < 2  # the box's bottom-left sits near the page's
    assert legend.y <= doc.page_height and legend.x + legend.width <= doc.page_width
    assert scale.x + scale.length > doc.page_width - 2 and scale.y < 2
    assert scale.length == 5 and scale.label == "5 ft"


def test_saved_positions_override_the_defaults():
    doc = SceneDocument(page_width=24, page_height=24, scale=36)
    doc.legend = Placement(10, 12)
    doc.scale_indicator = Placement(3, 20)
    legend = legend_layout(doc, [])
    scale = scale_indicator_layout(doc)
    assert (legend.x, legend.y) == (10, 12)
    assert (scale.x, scale.y) == (3, 20)


def _scene_copy() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="landscape-test-")) / "backyard.yaml"
    shutil.copy(BACKYARD, tmp)
    return tmp


def test_positions_parse_from_the_scene_file(tmp_path):
    scene = tmp_path / "s.yaml"
    scene.write_text(BACKYARD.read_text() + "\nlegend: {x: 1.5, y: 7}\nscale_indicator: {x: 15, y: 1}\n")
    doc = load_scene(scene)
    assert doc.legend == Placement(1.5, 7) and doc.scale_indicator == Placement(15, 1)
    assert load_scene(BACKYARD).legend is None  # absent until moved


def test_a_malformed_position_is_a_schema_error(tmp_path):
    scene = tmp_path / "s.yaml"
    scene.write_text(BACKYARD.read_text() + "\nlegend: {x: left}\n")
    with pytest.raises(SchemaError, match="legend"):
        load_scene(scene)


def test_moving_an_overlay_is_saved_undoable_and_marks_the_file_unsaved():
    path = _scene_copy()
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)

    session.set_overlay_position("legend", 2.25, 8.5)

    assert session.doc.legend == Placement(2.25, 8.5)
    assert session.dirty
    session.save()
    assert load_scene(path).legend == Placement(2.25, 8.5)
    session.undo()
    assert session.doc.legend is None


def test_an_unmoved_scene_still_saves_byte_identical():
    """Positions are only written once something is actually moved."""
    path = _scene_copy()
    original = path.read_bytes()
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)
    session.save()
    assert path.read_bytes() == original


def test_unknown_overlay_names_are_rejected():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy())
    with pytest.raises(ValueError):
        session.set_overlay_position("north_arrow", 1, 1)
