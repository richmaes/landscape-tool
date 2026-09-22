from pathlib import Path

import pytest

from landscape.schema import SchemaError
from landscape.scene_io import dump_raw, load_raw, load_scene, parse_scene

EXAMPLE_SCENE = Path(__file__).parent.parent / "scenes" / "example.yaml"


def test_load_example_scene():
    doc = load_scene(EXAMPLE_SCENE)
    assert doc.units == "ft"
    assert doc.scale == 36
    assert len(doc.objects) > 0
    ids = {obj.id for obj in doc.objects}
    assert "firepit" in ids
    assert "clearance_marker" in ids


def test_example_scene_covers_every_primitive_and_relation():
    doc = load_scene(EXAMPLE_SCENE)
    kinds = {obj.primitive.kind for obj in doc.objects if obj.primitive is not None}
    for expected in (
        "circle",
        "ellipse",
        "rect",
        "polygon",
        "regular_polygon",
        "line",
        "fence_line",
        "wavy_path",
        "walkway",
        "keepout",
    ):
        assert expected in kinds, f"example scene is missing a {expected!r} object"

    relations = {type(obj.relation).__name__ for obj in doc.objects if obj.relation}
    assert relations == {"CenterOf", "MirrorOf", "RelativeTo", "ChordOf"}

    assert any(obj.annotation for obj in doc.objects)
    assert any(obj.definition for obj in doc.objects)
    assert doc.get("shed").transform.rotation == 5

    lawn = doc.get("lawn")
    assert lawn.boolean.op == "difference"
    assert lawn.boolean.targets == ["bed_edge"]


def test_resolution_order_respects_dependencies():
    doc = load_scene(EXAMPLE_SCENE)
    order = doc.resolution_order
    assert order.index("bed_edge") < order.index("lawn")
    assert order.index("firepit") < order.index("firepit_keepout")
    assert order.index("deck_west") < order.index("deck_east")
    assert order.index("hot_tub_pad") < order.index("deck_south")


def test_round_trip_byte_identical(tmp_path):
    raw = load_raw(EXAMPLE_SCENE)
    out_path = tmp_path / "roundtrip.yaml"
    dump_raw(raw, out_path)
    assert out_path.read_text() == EXAMPLE_SCENE.read_text()


def test_missing_required_key_raises_with_location():
    with pytest.raises(SchemaError, match="page_width"):
        parse_scene({"units": "ft", "page_height": 10, "scale": 36})


def test_duplicate_object_id_rejected():
    with pytest.raises(SchemaError, match="duplicate object id"):
        parse_scene(
            {
                "page_width": 10,
                "page_height": 10,
                "scale": 36,
                "objects": [
                    {"id": "a", "type": "circle", "cx": 0, "cy": 0, "r": 1},
                    {"id": "a", "type": "circle", "cx": 1, "cy": 1, "r": 1},
                ],
            }
        )


def test_relation_to_unknown_object_rejected():
    with pytest.raises(SchemaError, match="unknown object"):
        parse_scene(
            {
                "page_width": 10,
                "page_height": 10,
                "scale": 36,
                "objects": [
                    {"id": "a", "type": "circle", "cx": 0, "cy": 0, "r": 1, "center_of": "ghost"},
                ],
            }
        )


def test_relation_cycle_detected():
    with pytest.raises(SchemaError, match="cycle"):
        parse_scene(
            {
                "page_width": 10,
                "page_height": 10,
                "scale": 36,
                "objects": [
                    {"id": "a", "type": "circle", "cx": 0, "cy": 0, "r": 1, "relative_to": "b"},
                    {"id": "b", "type": "circle", "cx": 0, "cy": 0, "r": 1, "relative_to": "a"},
                ],
            }
        )


def test_boolean_op_cycle_detected():
    with pytest.raises(SchemaError, match="cycle"):
        parse_scene(
            {
                "page_width": 10,
                "page_height": 10,
                "scale": 36,
                "objects": [
                    {
                        "id": "a",
                        "type": "circle",
                        "cx": 0,
                        "cy": 0,
                        "r": 1,
                        "boolean": {"op": "difference", "targets": ["b"]},
                    },
                    {
                        "id": "b",
                        "type": "circle",
                        "cx": 0,
                        "cy": 0,
                        "r": 1,
                        "boolean": {"op": "difference", "targets": ["a"]},
                    },
                ],
            }
        )


def test_boolean_op_unknown_target_rejected():
    with pytest.raises(SchemaError, match="unknown object"):
        parse_scene(
            {
                "page_width": 10,
                "page_height": 10,
                "scale": 36,
                "objects": [
                    {
                        "id": "a",
                        "type": "circle",
                        "cx": 0,
                        "cy": 0,
                        "r": 1,
                        "boolean": {"op": "difference", "targets": ["ghost"]},
                    },
                ],
            }
        )


def test_malformed_yaml_error_carries_line_number(tmp_path):
    bad_scene = tmp_path / "bad.yaml"
    bad_scene.write_text(
        "page_width: 10\n"
        "page_height: 10\n"
        "scale: 36\n"
        "objects:\n"
        "  - id: a\n"
        "    type: triangle\n"  # invalid on line 6
    )
    with pytest.raises(SchemaError) as exc_info:
        load_scene(bad_scene)
    assert exc_info.value.line == 5


def test_unknown_definition_reference_rejected():
    with pytest.raises(SchemaError, match="unknown definition"):
        parse_scene(
            {
                "page_width": 10,
                "page_height": 10,
                "scale": 36,
                "objects": [{"id": "a", "definition": "ghost"}],
            }
        )
