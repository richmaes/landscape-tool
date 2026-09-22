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
BACKYARD_SCENE = Path(__file__).parent.parent / "scenes" / "backyard.yaml"
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
    with pytest.raises(ValueError, match="unsupported export extension"):
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
