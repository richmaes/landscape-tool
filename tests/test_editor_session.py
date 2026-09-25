"""EditorSession tests. Deliberately does not import PySide6/pytest-qt —
the whole point of extracting this class out of EditorWindow was that
the editor's load/edit/save/rule-check logic is usable and testable
without Qt at all (see editor_session.py's module docstring)."""

import shutil
import tempfile
from pathlib import Path

import pytest

from landscape.editor_session import EditorSession
from landscape.geometry import resolve_scene

EXAMPLE_SCENE = Path(__file__).parent.parent / "scenes" / "example.yaml"
# The frozen original design (see the fixture's header), not the live
# scenes/backyard.yaml, which changes as Rich edits the design.
BACKYARD_SCENE = Path(__file__).parent / "fixtures" / "backyard_original.yaml"
BACKYARD_RULES = Path(__file__).parent.parent / "rules" / "backyard.yaml"
DEFAULT_MATERIALS = Path(__file__).parent.parent / "assets" / "materials.yaml"


def _scene_copy(path: Path) -> Path:
    """A private copy of a scene fixture, same filename, own temp
    directory. Loading EXAMPLE_SCENE/BACKYARD_SCENE directly and then
    editing it would write a `.autosave` sidecar next to the real
    fixture in the repo on every test run."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="landscape-test-"))
    copy_path = tmp_dir / path.name
    shutil.copy(path, copy_path)
    return copy_path


def test_editor_session_source_never_imports_qt():
    """A `sys.modules` check would be unreliable here: pytest runs every
    test file in one process, so test_editor.py importing PySide6 earlier
    in the same run would poison a runtime check regardless of what this
    module itself does. Checking the source text directly is what
    actually proves editor_session.py doesn't depend on Qt."""
    import landscape.editor_session as module

    source = Path(module.__file__).read_text()
    assert "import PySide6" not in source
    assert "from PySide6" not in source
    assert "import PyQt" not in source
    assert "from PyQt" not in source


def test_load_resolves_geometry_and_runs_rules():
    session = EditorSession(DEFAULT_MATERIALS, BACKYARD_RULES)
    session.load(_scene_copy(BACKYARD_SCENE))
    assert session.doc is not None
    assert session.resolved is not None
    assert len(session.resolved.objects) == len(session.doc.objects)
    assert {v.rule_id for v in session.violations} == {
        "no_burnable_in_firepit_keepout",
        "firepit_keepout_concentric",
        "firepit_keepout_contained_by_site",
    }


def test_load_without_rules_path_has_no_violations():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    assert session.violations == []


def test_set_rotation_updates_doc_and_recomputes():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 45)
    assert session.doc.get("shed").transform.rotation == 45
    # resolved geometry reflects the new rotation (recompute() ran)
    assert session.resolved.get("shed").geometry.equals(
        resolve_scene(session.doc).get("shed").geometry
    )


def test_set_scale_updates_doc():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_scale("shed", 2.5)
    assert session.doc.get("shed").transform.scale == 2.5


def test_set_material_updates_doc():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_material("shed", "water")
    assert session.doc.get("shed").material == "water"


def test_edits_recompute_violations_live():
    session = EditorSession(DEFAULT_MATERIALS, BACKYARD_RULES)
    session.load(_scene_copy(BACKYARD_SCENE))
    assert len(session.violations) == 3

    keepout = session.doc.get("firepit_keepout")
    firepit = session.doc.get("firepit")
    dx = firepit.primitive.cx - keepout.primitive.shape.cx
    dy = firepit.primitive.cy - keepout.primitive.shape.cy
    keepout.transform.tx += dx
    keepout.transform.ty += dy
    session.sync_object("firepit_keepout")
    session.recompute()

    assert "firepit_keepout_concentric" not in {v.rule_id for v in session.violations}


def test_save_unchanged_is_byte_identical(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    out = tmp_path / "roundtrip.yaml"
    session.save(out)
    assert out.read_text() == EXAMPLE_SCENE.read_text()


def test_save_after_set_rotation_touches_only_that_object(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 45)
    out = tmp_path / "edited.yaml"
    session.save(out)

    touched = ("shed", "transform", "tx:", "ty:", "rotation:", "scale:")
    unrelated_original = [l for l in EXAMPLE_SCENE.read_text().splitlines() if not any(t in l for t in touched)]
    unrelated_saved = [l for l in out.read_text().splitlines() if not any(t in l for t in touched)]
    assert unrelated_original == unrelated_saved


def test_save_defaults_to_loaded_scene_path(tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    session.save()  # no path given
    assert scene_copy.read_text() == EXAMPLE_SCENE.read_text()


def test_sync_object_skips_unknown_id():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.sync_object("does_not_exist")  # must not raise


# --- export ----------------------------------------------------------


def test_export_png(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    out = tmp_path / "out.png"
    session.export(out, show_legend=True, show_annotations=True)
    assert out.exists() and out.stat().st_size > 0


def test_export_svg(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    out = tmp_path / "out.svg"
    session.export(out)
    assert "<svg" in out.read_text()


def test_export_pdf(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    out = tmp_path / "out.pdf"
    session.export(out)
    assert out.read_bytes()[:4] == b"%PDF"


def test_export_rejects_unsupported_extension(tmp_path):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    with pytest.raises(ValueError, match="unsupported output type"):
        session.export(tmp_path / "out.jpg")


def test_export_reflects_edits():
    """Export renders session.resolved, so an edit made before exporting
    shows up in the output — not a stale snapshot from load()."""
    session = EditorSession(DEFAULT_MATERIALS, BACKYARD_RULES)
    session.load(_scene_copy(BACKYARD_SCENE))
    session.set_material("firepit", "water")
    assert session.resolved.get("firepit").material == "water"


# --- undo/redo ---------------------------------------------------------


def test_no_undo_or_redo_immediately_after_load():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    assert not session.can_undo
    assert not session.can_redo


# --- dirty flag (watch-and-reload's basis for warn-vs-auto-reload) ------


def test_not_dirty_immediately_after_load():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    assert not session.dirty


def test_dirty_after_an_edit():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 45)
    assert session.dirty


def test_not_dirty_after_save(tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    session.set_rotation("shed", 45)
    assert session.dirty

    session.save()

    assert not session.dirty


def test_not_dirty_after_undoing_back_to_the_saved_state():
    """Rich's call (2026-09-24): undoing every change since the last save
    means there's nothing unsaved, so the indicator should clear. (This
    used to stay dirty until an explicit save, by design.)"""
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 45)
    session.set_scale("shed", 2)
    session.undo()
    assert session.dirty  # one edit still applied
    session.undo()
    assert not session.dirty


def test_redo_past_the_saved_state_is_dirty_again():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 45)
    session.undo()
    session.redo()
    assert session.dirty


def test_undo_to_before_a_save_is_dirty(tmp_path):
    """The saved point is wherever save() happened, not the loaded file:
    undoing an edit that's already been saved leaves the document
    different from what's on disk."""
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    session.set_rotation("shed", 45)
    session.save()

    session.undo()

    assert session.dirty
    session.redo()
    assert not session.dirty


def test_a_fresh_edit_after_undoing_to_the_saved_state_is_dirty():
    """A new edit branches off the saved state; it must never be mistaken
    for the saved state just because the undo depth happens to match."""
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 45)
    session.undo()
    session.set_rotation("shed", 30)
    assert session.dirty


def test_save_as_makes_the_new_file_the_one_being_edited(tmp_path):
    """Save As switches the working file (standard desktop behaviour), so
    "saved" and the next plain Save refer to the new file — not a clean
    indicator for a file you're no longer writing to."""
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 45)
    new_path = tmp_path / "renamed.yaml"

    session.save(new_path)

    assert session.scene_path == new_path
    assert not session.dirty
    session.set_rotation("shed", 10)
    session.save()
    assert "rotation: 10" in new_path.read_text()


def test_on_state_change_fires_whenever_saved_status_can_change(tmp_path):
    """The GUI's unsaved indicator hangs off this, so it has to fire for
    every path that can flip `dirty` — including a plain drag, which
    calls `push_undo()` directly rather than any `set_*()`."""
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    calls = []
    session.on_state_change = lambda: calls.append(session.dirty)

    session.load(scene_copy)
    session.push_undo()  # what a drag does at its start
    session.undo()
    session.redo()
    session.save()

    assert calls == [False, True, False, True, False]


def test_undo_reverts_a_set_rotation():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    before = session.doc.get("shed").transform.rotation
    session.set_rotation("shed", 77)
    assert session.can_undo

    session.undo()

    assert session.doc.get("shed").transform.rotation == before
    assert not session.can_undo
    assert session.can_redo


def test_redo_reapplies_an_undone_edit():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 77)
    session.undo()

    session.redo()

    assert session.doc.get("shed").transform.rotation == 77
    assert not session.can_redo


def test_new_edit_after_undo_clears_redo_stack():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_rotation("shed", 77)
    session.undo()
    assert session.can_redo

    session.set_scale("shed", 2.0)

    assert not session.can_redo


def test_undo_recomputes_resolved_and_violations():
    session = EditorSession(DEFAULT_MATERIALS, BACKYARD_RULES)
    session.load(_scene_copy(BACKYARD_SCENE))
    original_geom = session.resolved.get("firepit_keepout").geometry

    keepout = session.doc.get("firepit_keepout")
    firepit = session.doc.get("firepit")
    session.push_undo()
    keepout.transform.tx += firepit.primitive.cx - keepout.primitive.shape.cx
    keepout.transform.ty += firepit.primitive.cy - keepout.primitive.shape.cy
    session.recompute()
    assert "firepit_keepout_concentric" not in {v.rule_id for v in session.violations}

    session.undo()

    assert "firepit_keepout_concentric" in {v.rule_id for v in session.violations}
    assert session.resolved.get("firepit_keepout").geometry.equals(original_geom)


def test_undo_on_empty_stack_is_a_noop():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.undo()  # must not raise
    assert session.doc is not None


def test_undo_does_not_affect_the_saved_file_until_save_is_called(tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    session.set_rotation("shed", 77)
    session.undo()
    session.save()
    assert scene_copy.read_text() == EXAMPLE_SCENE.read_text()


# --- autosave ------------------------------------------------------------


def test_autosave_written_after_an_edit(tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    autosave_path = tmp_path / "copy.yaml.autosave"
    assert not autosave_path.exists()

    session.set_rotation("shed", 77)

    assert autosave_path.exists()
    from landscape.scene_io import load_scene as parse_saved

    assert parse_saved(autosave_path).get("shed").transform.rotation == 77


def test_autosave_removed_after_explicit_save(tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    session.set_rotation("shed", 77)
    autosave_path = tmp_path / "copy.yaml.autosave"
    assert autosave_path.exists()

    session.save()

    assert not autosave_path.exists()


# --- create_object -------------------------------------------------------


def test_create_object_returns_a_unique_generated_id():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    first = session.create_object("circle")
    second = session.create_object("circle")
    assert first == "circle_1"
    assert second == "circle_2"


def test_create_object_is_centered_on_the_page():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    new_id = session.create_object("circle")
    circle = session.doc.get(new_id).primitive
    assert circle.cx == session.doc.page_width / 2
    assert circle.cy == session.doc.page_height / 2


def test_create_object_is_added_to_doc_and_resolution_order():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    before = len(session.doc.objects)
    new_id = session.create_object("rect")
    assert len(session.doc.objects) == before + 1
    assert new_id in session.doc.resolution_order
    assert session.resolved.get(new_id) is not None


def test_create_object_rejects_keepout():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    with pytest.raises(ValueError, match="cannot create a 'keepout'"):
        session.create_object("keepout")


def test_create_object_is_undoable():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    before = len(session.doc.objects)
    session.create_object("circle")

    session.undo()

    assert len(session.doc.objects) == before


@pytest.mark.parametrize("kind", ["circle", "ellipse", "rect", "polygon", "regular_polygon", "line", "fence_line", "wavy_path", "walkway"])
def test_create_object_every_creatable_kind_resolves(kind):
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    new_id = session.create_object(kind)
    assert session.resolved.get(new_id) is not None


def test_create_object_saves_correctly_and_reloads(tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    original_object_count = len(session.doc.objects)
    new_id = session.create_object("circle")

    session.save()

    from landscape.scene_io import load_scene as parse_saved

    reloaded = parse_saved(scene_copy)
    assert len(reloaded.objects) == original_object_count + 1
    assert reloaded.get(new_id).primitive.r == 1.0


def test_create_object_does_not_disturb_untouched_objects(tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    session.create_object("circle")
    session.save()

    original_lines = EXAMPLE_SCENE.read_text().splitlines()
    saved_lines = scene_copy.read_text().splitlines()
    assert saved_lines[: len(original_lines)] == original_lines


# --- set_relation --------------------------------------------------------


def test_set_relation_center_of():
    from landscape.schema import CenterOf

    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_relation("deck_west", "center_of", "firepit")

    assert session.doc.get("deck_west").relation == CenterOf(ref="firepit")
    deck_centroid = session.resolved.get("deck_west").geometry.centroid
    firepit_centroid = session.resolved.get("firepit").geometry.centroid
    assert deck_centroid.distance(firepit_centroid) < 1e-6


def test_set_relation_mirror_of_with_param():
    from landscape.schema import MirrorOf

    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_relation("water_feature_a", "mirror_of", "deck_west", about_x=10)

    assert session.doc.get("water_feature_a").relation == MirrorOf(ref="deck_west", about_x=10, about_y=None)


def test_set_relation_clears_previous_relation_type():
    """deck_east starts with mirror_of deck_west/about_x=30 in
    example.yaml; switching it to center_of must not leave stale
    mirror_of/about_x keys in the raw document."""
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))

    session.set_relation("deck_east", "center_of", "firepit")

    raw_obj = session.raw_objects["deck_east"]
    assert "mirror_of" not in raw_obj
    assert "about_x" not in raw_obj
    assert raw_obj["center_of"] == "firepit"


def test_clear_relation():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    assert session.doc.get("deck_east").relation is not None

    session.set_relation("deck_east", None)

    assert session.doc.get("deck_east").relation is None
    assert "mirror_of" not in session.raw_objects["deck_east"]


def test_set_relation_rejects_unknown_type():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    with pytest.raises(ValueError, match="unknown relation type"):
        session.set_relation("deck_west", "not_a_real_relation", "firepit")


def test_set_relation_requires_a_target():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    with pytest.raises(ValueError, match="requires a target"):
        session.set_relation("deck_west", "center_of", None)


def test_set_relation_rejects_unknown_ref_and_rolls_back():
    from landscape.schema import SchemaError

    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    with pytest.raises(SchemaError, match="unknown object"):
        session.set_relation("deck_west", "center_of", "does_not_exist")

    assert session.doc.get("deck_west").relation is None
    assert not session.can_undo  # the push_undo() for the failed edit was popped back off


def test_set_relation_rejects_a_cycle_and_rolls_back():
    from landscape.schema import SchemaError

    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    original_order = list(session.doc.resolution_order)
    with pytest.raises(SchemaError, match="cycle"):
        session.set_relation("deck_west", "relative_to", "deck_west", dx=0, dy=0)

    assert session.doc.get("deck_west").relation is None
    assert session.doc.resolution_order == original_order
    assert not session.dirty  # a rejected edit leaves nothing to save


def test_set_relation_is_undoable_on_success():
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(_scene_copy(EXAMPLE_SCENE))
    session.set_relation("deck_west", "center_of", "firepit")
    assert session.can_undo

    session.undo()

    assert session.doc.get("deck_west").relation is None


def test_set_relation_saves_and_reloads_correctly(tmp_path):
    scene_copy = tmp_path / "copy.yaml"
    scene_copy.write_text(EXAMPLE_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene_copy)
    session.set_relation("deck_west", "center_of", "firepit")
    session.save()

    from landscape.schema import CenterOf
    from landscape.scene_io import load_scene as parse_saved

    reloaded = parse_saved(scene_copy)
    assert reloaded.get("deck_west").relation == CenterOf(ref="firepit")


# --- saved YAML keeps the blank line between objects ------------------------


def _block_after(text: str, object_id: str) -> str:
    """The saved text from `- id: <object_id>` up to (not including) the
    next object's `- id:` line."""
    start = text.index(f"- id: {object_id}\n")
    end = text.index("  - id:", start + 1)
    return text[start:end]


def test_adding_a_transform_keeps_the_blank_line_after_the_object(tmp_path):
    """A real formatting bug found in Rich's own saved backyard.yaml: ruamel
    keeps the blank line between objects as a comment on the object's
    *last* key, so appending a new `transform:` key put it *after* that
    blank line — the gap ended up above `transform:` instead of below it."""
    scene = tmp_path / "backyard.yaml"
    scene.write_text(BACKYARD_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene)

    session.set_scale("firepit_keepout", 0.8)
    session.save()

    block = _block_after(scene.read_text(), "firepit_keepout")
    assert "    z: 18\n    transform:\n" in block  # no gap inside the object
    assert block.endswith("\n\n")  # exactly one blank line before the next object
    assert not block.endswith("\n\n\n")


def test_rewriting_an_existing_transform_keeps_the_blank_line(tmp_path):
    """Once `transform:` is the last key, the blank line lives on *its*
    last nested key — replacing the whole transform mapping on the next
    edit must not drop it."""
    scene = tmp_path / "backyard.yaml"
    scene.write_text(BACKYARD_SCENE.read_text())
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene)
    session.set_scale("firepit_keepout", 0.8)
    session.save()

    session.load(scene)
    session.set_rotation("firepit_keepout", 15)
    session.save()

    block = _block_after(scene.read_text(), "firepit_keepout")
    assert "rotation: 15" in block
    assert block.endswith("\n\n") and not block.endswith("\n\n\n")


def test_set_pattern_is_saved_and_undoable(tmp_path):
    from landscape.scene_io import load_scene

    scene = tmp_path / "s.yaml"
    scene.write_text(
        "page_width: 10\npage_height: 10\nscale: 36\nobjects:\n"
        "  - id: patio\n    type: rect\n    x: 0\n    y: 0\n    width: 10\n    height: 10\n"
        "    material: pavers_light_grey\n"
    )
    session = EditorSession(DEFAULT_MATERIALS)
    session.load(scene)

    session.set_pattern("patio", "basketweave")

    assert session.resolved.get("patio").pattern == "basketweave"
    session.save()
    assert load_scene(scene).get("patio").pattern == "basketweave"
    session.undo()
    assert session.doc.get("patio").pattern is None
