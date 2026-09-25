"""Editing an object's size directly (not just its uniform scale): reading
the editable dimensions of each shape type, reshaping in one or both
dimensions about the object's centre, and writing it back to the YAML."""

import pytest
from shapely.geometry import box

from landscape.dimensions import object_dimensions, resized_primitive
from landscape.editor_session import EditorSession
from landscape.geometry import primitive_to_geometry
from landscape.scene_io import load_scene
from landscape.schema import (
    Circle,
    Ellipse,
    FenceLine,
    Keepout,
    Line,
    Polygon,
    Rect,
    RegularPolygon,
    SceneObject,
    Transform,
)

DEFAULT_MATERIALS = "assets/materials.yaml"


def _obj(primitive, scale=1.0, **kw):
    return SceneObject(id="o", primitive=primitive, transform=Transform(scale=scale), **kw)


def _centre(primitive):
    c = primitive_to_geometry(primitive).centroid
    return round(c.x, 6), round(c.y, 6)


@pytest.mark.parametrize(
    "primitive, expected",
    [
        (Rect(x=2, y=2, width=6, height=4, rotation=30), (6, 4, False)),
        (Ellipse(cx=0, cy=0, rx=2, ry=1), (4, 2, False)),
        (Circle(cx=0, cy=0, r=1.5), (3, 3, True)),
        (RegularPolygon(cx=0, cy=0, sides=6, size=1), (2, 2, True)),
        (Polygon(points=[(0, 0), (4, 0), (4, 2), (0, 2)]), (4, 2, False)),
        (Line(x1=0, y1=0, x2=3, y2=4), (3, 4, False)),
        (Keepout(shape=Circle(cx=0, cy=0, r=6), rule="r"), (12, 12, True)),
    ],
)
def test_editable_dimensions_by_shape(primitive, expected):
    dims = object_dimensions(_obj(primitive))
    assert (dims.width, dims.height, dims.diameter_only) == pytest.approx(expected)


def test_dimensions_include_the_objects_scale():
    dims = object_dimensions(_obj(Rect(width=6, height=4), scale=1.5))
    assert (dims.width, dims.height) == pytest.approx((9, 6))


def test_a_flat_dimension_is_not_offered():
    """A straight horizontal fence has no height to stretch."""
    dims = object_dimensions(_obj(FenceLine(points=[(0, 0), (24, 0)])))
    assert dims.width == pytest.approx(24) and dims.height is None


def test_instances_of_a_shared_definition_are_not_resizable_here():
    assert object_dimensions(_obj(Rect(width=1, height=1), definition="bench")) is None


def test_resizing_a_rect_in_one_dimension_keeps_its_centre_and_the_other_dimension():
    rect = Rect(x=2, y=2, width=6, height=4, rotation=30)
    new = resized_primitive(_obj(rect), width=10)
    assert (new.width, new.height, new.rotation) == (10, 4, 30)
    assert _centre(new) == _centre(rect)


def test_resizing_divides_out_the_objects_scale():
    """Typing 9 ft on an object drawn at 1.5x sets its own width to 6."""
    new = resized_primitive(_obj(Rect(width=4, height=4), scale=1.5), width=9, height=3)
    assert (new.width, new.height) == pytest.approx((6, 2))


def test_resizing_an_ellipse_and_a_circle():
    assert (resized_primitive(_obj(Ellipse(rx=2, ry=1)), height=5).ry, ) == (2.5,)
    assert resized_primitive(_obj(Circle(cx=3, cy=3, r=1)), width=5).r == 2.5


def test_resizing_points_stretches_them_about_the_centre():
    square = Polygon(points=[(0, 0), (4, 0), (4, 4), (0, 4)])
    new = resized_primitive(_obj(square), width=8)
    assert primitive_to_geometry(new).bounds == pytest.approx((-2, 0, 6, 4))


def test_resizing_a_keepout_resizes_its_shape():
    new = resized_primitive(_obj(Keepout(shape=Circle(cx=0, cy=0, r=6), rule="r")), width=8)
    assert new.shape.r == 4 and new.rule == "r"


# --- through the session: undoable, saved, formatting kept ----------------------------


def _scene(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        "page_width: 20\npage_height: 20\nscale: 36\nobjects:\n"
        "  - id: shed\n    type: rect\n    x: 2\n    y: 2\n    width: 6\n    height: 4\n    material: deck\n\n"
        "  - id: path\n    type: walkway\n    points: [[0, 10], [10, 15]]\n    width: 3\n"
    )
    return path


def test_set_dimensions_reshapes_saves_and_undoes(tmp_path):
    path = _scene(tmp_path)
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)

    session.set_dimensions("shed", height=5)

    assert session.resolved.get("shed").geometry.bounds == pytest.approx((2, 1.5, 8, 6.5))
    assert session.dirty
    session.save()
    saved = load_scene(path).get("shed").primitive
    assert (saved.width, saved.height, saved.y) == (6, 5, 1.5)
    session.undo()
    assert session.doc.get("shed").primitive.height == 4


def test_set_dimensions_keeps_the_yaml_tidy(tmp_path):
    """Only the changed numbers are rewritten; points stay a compact flow
    list and the blank line between objects stays put."""
    path = _scene(tmp_path)
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(path)

    session.set_dimensions("path", width=20)
    session.save()

    text = path.read_text()
    assert "    points: [[-5, 10], [15, 15]]\n" in text
    assert "    material: deck\n\n  - id: path\n" in text
    assert "type: rect\n    x: 2\n" in text  # untouched object unchanged


def test_set_dimensions_rejects_what_it_cant_resize(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene(tmp_path))
    with pytest.raises(ValueError):
        session.set_dimensions("shed", width=0)
