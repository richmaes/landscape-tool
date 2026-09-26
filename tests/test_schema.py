import pytest

from landscape.schema import (
    ChordOf,
    CenterOf,
    MirrorOf,
    PRIMITIVE_TYPES,
    RelativeTo,
    SchemaError,
    parse_boolean,
    parse_primitive,
    parse_relation,
    parse_transform,
    primitive_to_raw_dict,
)


def test_parse_circle():
    prim = parse_primitive({"type": "circle", "cx": 1, "cy": 2, "r": 3})
    assert prim.cx == 1 and prim.cy == 2 and prim.r == 3


def test_parse_unknown_type_raises():
    with pytest.raises(SchemaError, match="unknown primitive type"):
        parse_primitive({"type": "triangle"})


def test_parse_polygon_points_become_tuples():
    prim = parse_primitive({"type": "polygon", "points": [[0, 0], [1, 0], [1, 1]]})
    assert prim.points == [(0, 0), (1, 0), (1, 1)]


def test_parse_keepout_wraps_shape():
    prim = parse_primitive(
        {"type": "keepout", "rule": "no_burnable", "shape": {"type": "circle", "cx": 0, "cy": 0, "r": 6}}
    )
    assert prim.rule == "no_burnable"
    assert prim.shape.r == 6


def test_wavy_path_rejects_out_of_range_waviness():
    with pytest.raises(SchemaError, match="waviness"):
        parse_primitive({"type": "wavy_path", "points": [], "waviness": 1.5})


def test_parse_relation_center_of():
    rel = parse_relation({"center_of": "firepit"})
    assert rel == CenterOf(ref="firepit")


def test_parse_relation_mirror_of_flat_siblings():
    rel = parse_relation({"mirror_of": "deck_west", "about_x": 30})
    assert rel == MirrorOf(ref="deck_west", about_x=30, about_y=None)


def test_mirror_of_requires_exactly_one_axis():
    with pytest.raises(SchemaError, match="exactly one"):
        parse_relation({"mirror_of": "deck_west", "about_x": 30, "about_y": 5})
    with pytest.raises(SchemaError, match="exactly one"):
        parse_relation({"mirror_of": "deck_west"})


def test_parse_relation_relative_to():
    rel = parse_relation({"relative_to": "hot_tub_pad", "dx": 0, "dy": -2})
    assert rel == RelativeTo(ref="hot_tub_pad", dx=0, dy=-2)


def test_parse_relation_chord_of_requires_offset():
    with pytest.raises(SchemaError, match="offset"):
        parse_relation({"chord_of": "site_circle"})
    rel = parse_relation({"chord_of": "site_circle", "offset": -2.26})
    assert rel == ChordOf(ref="site_circle", offset=-2.26, angle_deg=0.0)


def test_no_relation_present_returns_none():
    assert parse_relation({"type": "circle"}) is None


def test_multiple_relations_rejected():
    with pytest.raises(SchemaError, match="more than one relation"):
        parse_relation({"center_of": "a", "relative_to": "b"})


def test_parse_boolean_difference():
    op = parse_boolean({"op": "difference", "targets": ["bed_a", "bed_b"]})
    assert op.op == "difference"
    assert op.targets == ["bed_a", "bed_b"]


def test_boolean_rejects_invalid_op():
    with pytest.raises(SchemaError, match="boolean op must be one of"):
        parse_boolean({"op": "xor", "targets": ["a"]})


def test_boolean_requires_targets():
    with pytest.raises(SchemaError, match="at least one target"):
        parse_boolean({"op": "union", "targets": []})


def test_parse_boolean_none_when_absent():
    assert parse_boolean(None) is None


def test_parse_transform_defaults_to_identity():
    t = parse_transform(None)
    assert (t.tx, t.ty, t.rotation, t.scale) == (0.0, 0.0, 0.0, 1.0)


def test_parse_transform_rejects_unknown_field():
    with pytest.raises(SchemaError, match="unknown transform field"):
        parse_transform({"skew": 3})


# --- primitive_to_raw_dict: round-trips for every primitive kind --------

_SAMPLE_PRIMITIVE_DATA = {
    "circle": {"type": "circle", "cx": 1, "cy": 2, "r": 3},
    "ellipse": {"type": "ellipse", "cx": 1, "cy": 2, "rx": 3, "ry": 4},
    "rect": {"type": "rect", "x": 1, "y": 2, "width": 3, "height": 4, "rotation": 5, "corner_r": 0.5},
    "polygon": {"type": "polygon", "points": [[0, 0], [1, 0], [1, 1]]},
    "regular_polygon": {"type": "regular_polygon", "cx": 1, "cy": 2, "sides": 6, "size": 1},
    "line": {"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
    "fence_line": {"type": "fence_line", "points": [[0, 0], [1, 0]], "post_size": 0.5},
    "wavy_path": {"type": "wavy_path", "points": [[0, 0], [1, 0]], "waviness": 0.4, "seed": 7},
    "model": {"type": "model", "file": "bench.glb", "x": 5, "y": 5, "width": 4, "depth": 2, "height": 3,
              "rotation": 15, "up": "y"},
    "walkway": {"type": "walkway", "points": [[0, 0], [1, 0]], "width": 2},
    "keepout": {
        "type": "keepout",
        "rule": "no_burnable_material",
        "shape": {"type": "circle", "cx": 0, "cy": 0, "r": 6},
    },
}


@pytest.mark.parametrize("kind", sorted(PRIMITIVE_TYPES))
def test_primitive_to_raw_dict_round_trips(kind):
    original = parse_primitive(_SAMPLE_PRIMITIVE_DATA[kind])
    raw = primitive_to_raw_dict(original)
    assert raw["type"] == kind
    assert parse_primitive(raw) == original


def test_primitive_to_raw_dict_points_are_plain_lists_not_tuples():
    raw = primitive_to_raw_dict(parse_primitive({"type": "polygon", "points": [[0, 0], [1, 1]]}))
    assert raw["points"] == [[0, 0], [1, 1]]
    assert all(isinstance(p, list) for p in raw["points"])


def test_an_object_can_choose_a_paver_pattern(tmp_path):
    from landscape.scene_io import load_scene

    scene = tmp_path / "s.yaml"
    scene.write_text(
        "page_width: 10\npage_height: 10\nscale: 36\nobjects:\n"
        "  - id: patio\n    type: rect\n    x: 0\n    y: 0\n    width: 10\n    height: 10\n"
        "    material: pavers_light_grey\n    pattern: running_bond\n"
    )
    assert load_scene(scene).get("patio").pattern == "running_bond"


def test_an_unknown_paver_pattern_is_a_schema_error_with_its_line(tmp_path):
    import pytest

    from landscape.scene_io import load_scene
    from landscape.schema import SchemaError

    scene = tmp_path / "s.yaml"
    scene.write_text(
        "page_width: 10\npage_height: 10\nscale: 36\nobjects:\n"
        "  - id: patio\n    type: rect\n    x: 0\n    y: 0\n    width: 10\n    height: 10\n    pattern: zigzag\n"
    )
    with pytest.raises(SchemaError, match="pattern") as excinfo:
        load_scene(scene)
    assert excinfo.value.line == 5
