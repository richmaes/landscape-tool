"""Regression tests for the real backyard scene (M1's leftover item):
the design as converted from extraction/objects.json, and
rules/backyard.yaml, which is expected to reproduce the real design
flaws Rich already documented by hand in extraction/objects.md.

Those checks run against a frozen copy, tests/fixtures/backyard_original.yaml:
the live scenes/backyard.yaml is Rich's working design and is meant to
change (on 2026-09-24 he recentred and shrank the firepit keepout, fixing
several of the very flaws these tests pin down). The live file only gets
the design-independent checks at the bottom of this module."""

from pathlib import Path

import pytest

from landscape.geometry import resolve_scene
from landscape.materials import color_distance, load_materials
from landscape.rules import load_rules, run_rules
from landscape.scene_io import load_scene

# The frozen original design (see the fixture's header), not the live
# scenes/backyard.yaml, which changes as Rich edits the design.
BACKYARD_SCENE = Path(__file__).parent / "fixtures" / "backyard_original.yaml"
LIVE_BACKYARD_SCENE = Path(__file__).parent.parent / "scenes" / "backyard.yaml"
BACKYARD_RULES = Path(__file__).parent.parent / "rules" / "backyard.yaml"
DEFAULT_MATERIALS = Path(__file__).parent.parent / "assets" / "materials.yaml"


def test_backyard_scene_matches_extraction_object_count():
    doc = load_scene(BACKYARD_SCENE)
    assert len(doc.objects) == 20  # extraction/objects.json has 20 objects


def test_backyard_scene_matches_source_scale_and_extent():
    doc = load_scene(BACKYARD_SCENE)
    assert (doc.page_width, doc.page_height, doc.scale) == (24, 24, 36)


def test_keepout_not_centered_on_firepit_matches_documented_offset():
    """extraction/objects.json: firepit is 0.792 ft off the keepout's own
    center ("keepout_not_centred_on_firepit")."""
    scene = resolve_scene(load_scene(BACKYARD_SCENE))
    distance = scene.get("firepit_keepout").geometry.centroid.distance(
        scene.get("firepit").geometry.centroid
    )
    assert distance == pytest.approx(0.792, abs=0.001)


def test_keepout_escapes_site_circle_matches_documented_overhang():
    """extraction/objects.json: centres are 7.819 ft apart, r=6+12=18... the
    keepout overhangs the site circle. Checked here via distance between
    centers, the number objects.json itself reports."""
    scene = resolve_scene(load_scene(BACKYARD_SCENE))
    distance = scene.get("firepit_keepout").geometry.centroid.distance(
        scene.get("site_circle").geometry.centroid
    )
    assert distance == pytest.approx(7.819, abs=0.01)


def test_deck_s_does_not_actually_touch_the_drawn_keepout():
    """The keepout circle AS DRAWN (not a hypothetical recentered one) is
    0.675 ft clear of deck_s. extraction/objects.json's "0.085 ft
    intrusion" finding is measured from the firepit's own center instead
    — what the clearance would be if the concentricity flaw got fixed
    first, not what the current drawing actually has."""
    scene = resolve_scene(load_scene(BACKYARD_SCENE))
    deck_s = scene.get("deck_s").geometry
    keepout = scene.get("firepit_keepout").geometry
    firepit = scene.get("firepit").geometry

    assert not deck_s.intersects(keepout)
    assert deck_s.distance(keepout) == pytest.approx(0.675, abs=0.001)
    assert deck_s.distance(firepit.centroid) == pytest.approx(5.915, abs=0.001)


def test_backyard_rules_reproduce_exactly_the_documented_flaws():
    scene = resolve_scene(load_scene(BACKYARD_SCENE))
    violations = run_rules(scene, load_rules(BACKYARD_RULES))
    fired = {v.rule_id for v in violations}
    assert fired == {
        "no_burnable_in_firepit_keepout",
        "firepit_keepout_concentric",
        "firepit_keepout_contained_by_site",
    }
    assert "no_unintended_overlaps" not in fired  # legitimate overlaps are all in the exceptions list


def test_sand_placeholder_and_fence_colors_are_borderline_close():
    """Not a bug, a documented observation: these two colors sit just
    above the 0.12 'too similar' threshold (0.124), but read as nearly
    identical in an actual render (back_fence all but disappears into
    site_circle). Locks in the measured distance so a future palette
    change doesn't silently drift further apart or closer without
    anyone noticing either way."""
    lib = load_materials(DEFAULT_MATERIALS)
    distance = color_distance(lib.resolve("fence").color, lib.resolve("sand_tbd").color)
    assert distance == pytest.approx(0.124, abs=0.001)


# --- the live, editable design ----------------------------------------------
# Deliberately design-independent: these must keep passing whatever Rich
# changes in the editor. Specific geometry belongs in the frozen fixture.


def test_live_backyard_scene_loads_resolves_and_runs_rules():
    doc = load_scene(LIVE_BACKYARD_SCENE)
    scene = resolve_scene(doc)
    assert {o.id for o in scene.objects} == {o.id for o in doc.objects}
    assert all(not o.geometry.is_empty for o in scene.objects)
    run_rules(scene, load_rules(BACKYARD_RULES))  # must not raise; results are the design's business
