"""Moving objects in the editor, end to end: a real mouse drag must move
the object in the document, in the editor's resolved geometry (what the
art preview, the rule checker and every redraw use), in the saved file,
and in both views — and be undoable.

Written for a real bug (2026-09-25): a plain drag updated the document
and the saved YAML, but never recomputed the resolved geometry, so the art
preview painted the object at its old spot and switching back to Design
redrew it there too — it looked as if the move hadn't saved.
"""

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from landscape.editor import EditorWindow  # noqa: E402
from landscape.geometry import resolve_scene  # noqa: E402
from landscape.scene_io import load_scene  # noqa: E402

from test_editor import _answer_close_prompts_with_discard, _mouse_drag, art_calls  # noqa: E402,F401

FIXTURE = Path(__file__).parent / "fixtures" / "movement.yaml"
MATERIALS = Path(__file__).parent.parent / "assets" / "materials.yaml"
RULES = Path(__file__).parent / "fixtures" / "movement_rules.yaml"
DX, DY = 1.5, -1.0  # feet, +y north
TOL = 0.1  # a drag lands on whole pixels

# Where to grab each object: a point only it covers (on the outline for the
# dashed ones and the ring, on the line for the seam).
GRAB = {
    "bed": (7, 3.5),
    "firepit": (15, 4),
    "firepit_keepout": (15 + 2.5, 4),
    "feature": (3, 13),
    "fence": (10, 19),
    "seam": (9, 8),
    "marker": (14, 10.5),
    "pond": (10, 13),
    "pond_border": (10 + 3.17, 13),
}


def _open(qtbot) -> tuple[EditorWindow, Path]:
    path = Path(tempfile.mkdtemp(prefix="landscape-move-")) / "movement.yaml"
    shutil.copy(FIXTURE, path)
    window = EditorWindow(materials_path=MATERIALS, rules_path=RULES)
    qtbot.addWidget(window)
    window.resize(1000, 800)
    window.show()
    qtbot.waitExposed(window)
    window.load_scene(path, show_annotations=True)
    return window, path


def _centre(window: EditorWindow, object_id: str) -> tuple[float, float]:
    c = window.session.resolved.get(object_id).geometry.centroid
    return c.x, c.y


def _drag(window: EditorWindow, object_id: str, dx: float = DX, dy: float = DY) -> None:
    h = window.session.doc.page_height
    x, y = GRAB[object_id]
    _mouse_drag(window._view, QPointF(x, h - y), QPointF(x + dx, h - (y + dy)), steps=4)
    QApplication.processEvents()  # let the post-drag redraw run


def _design_item_centre(window: EditorWindow, object_id: str) -> tuple[float, float]:
    """Centre of the object's canvas outline, back in scene feet."""
    item = next(i for i in window._view.scene().items() if i.data(0) == object_id)
    r = item.mapToScene(item.path()).boundingRect()
    return r.center().x(), window.session.doc.page_height - r.center().y()


def _moved(before, after, dx=DX, dy=DY):
    return after[0] == pytest.approx(before[0] + dx, abs=TOL) and after[1] == pytest.approx(before[1] + dy, abs=TOL)


@pytest.mark.parametrize("object_id", list(GRAB))
def test_a_drag_moves_the_object_everywhere_it_is_used(qtbot, object_id):
    window, _ = _open(qtbot)
    before = _centre(window, object_id)
    design_before = _design_item_centre(window, object_id)

    _drag(window, object_id)

    assert window._selected_id == object_id or window._selected_id is None  # grabbed the right thing
    assert _moved(before, _centre(window, object_id)), "resolved geometry (art preview, rules, redraws) is stale"
    assert _moved(design_before, _design_item_centre(window, object_id)), "the design canvas didn't keep the move"


@pytest.mark.parametrize("object_id", list(GRAB))
def test_a_moved_object_saves_to_the_yaml(qtbot, object_id):
    window, path = _open(qtbot)
    before = _centre(window, object_id)

    _drag(window, object_id)
    window.save_scene()

    reloaded = resolve_scene(load_scene(path)).get(object_id).geometry.centroid
    assert _moved(before, (reloaded.x, reloaded.y))


def test_the_art_preview_paints_a_moved_object_at_its_new_place(qtbot, art_calls):
    """Rich's report: move the firepit, switch to Art preview — it was back
    at its old spot, even after saving."""
    window, _ = _open(qtbot)
    window._art_action.trigger()  # paint once before the move, so a stale cache would show
    window._design_action.trigger()
    before = _centre(window, "firepit")

    _drag(window, "firepit")
    window.save_scene()
    window._art_action.trigger()

    painted = art_calls[-1]["centres"]["firepit"]
    assert _moved(before, painted)


def test_switching_views_after_a_move_keeps_it(qtbot):
    window, _ = _open(qtbot)
    before = _design_item_centre(window, "firepit")
    _drag(window, "firepit")

    window._art_action.trigger()
    window._design_action.trigger()

    assert _moved(before, _design_item_centre(window, "firepit"))


def test_moving_the_firepit_and_its_keepout_together(qtbot):
    """The exact pair from the report, one after the other, then saved."""
    window, path = _open(qtbot)
    pit, zone = _centre(window, "firepit"), _centre(window, "firepit_keepout")

    _drag(window, "firepit")
    _drag(window, "firepit_keepout")
    window.save_scene()

    saved = resolve_scene(load_scene(path))
    for object_id, before in (("firepit", pit), ("firepit_keepout", zone)):
        c = saved.get(object_id).geometry.centroid
        assert _moved(before, (c.x, c.y)), object_id


def test_two_drags_accumulate(qtbot):
    window, path = _open(qtbot)
    before = _centre(window, "bed")
    _drag(window, "bed")
    GRAB["bed"], original = (7 + DX, 3.5 + DY), GRAB["bed"]
    try:
        _drag(window, "bed")
    finally:
        GRAB["bed"] = original
    assert _moved(before, _centre(window, "bed"), 2 * DX, 2 * DY)
    window.save_scene()
    c = resolve_scene(load_scene(path)).get("bed").geometry.centroid
    assert _moved(before, (c.x, c.y), 2 * DX, 2 * DY)


def test_undo_puts_a_moved_object_back_everywhere(qtbot):
    window, _ = _open(qtbot)
    before, design_before = _centre(window, "bed"), _design_item_centre(window, "bed")
    _drag(window, "bed")

    window._on_undo()

    assert _centre(window, "bed") == pytest.approx(before, abs=1e-6)
    assert _design_item_centre(window, "bed") == pytest.approx(design_before, abs=1e-6)


def test_dependents_follow_a_moved_object(qtbot):
    """The paver ring is centred on the pond and has the pond cut out of it:
    moving the pond has to move the ring with it."""
    window, _ = _open(qtbot)
    _drag(window, "pond")
    pond, ring = _centre(window, "pond"), _centre(window, "pond_border")
    assert ring == pytest.approx(pond, abs=1e-3)


def test_rules_are_rechecked_after_a_move(qtbot):
    """Moving the keep-out off-centre from the firepit must raise the
    concentricity warning straight away, not at some later edit."""
    window, _ = _open(qtbot)
    assert not [v for v in window.session.violations if v.rule_id == "firepit_keepout_concentric"]

    _drag(window, "firepit_keepout", 1.0, 0.0)

    assert [v for v in window.session.violations if v.rule_id == "firepit_keepout_concentric"]
