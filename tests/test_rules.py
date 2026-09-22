from pathlib import Path

import pytest
from shapely.geometry import box

from landscape.geometry import ResolvedObject, ResolvedScene, resolve_scene
from landscape.rules import load_rules, run_rules
from landscape.scene_io import load_scene

EXAMPLE_SCENE = Path(__file__).parent.parent / "scenes" / "example.yaml"
DEFAULT_RULES = Path(__file__).parent.parent / "rules" / "default.yaml"


def _obj(id, geom, material=None, z=0, annotation=False, rule=None):
    return ResolvedObject(id=id, geometry=geom, material=material, layer="default", z=z, annotation=annotation, rule=rule)


# --- generic engine -------------------------------------------------------


def test_unknown_rule_type_raises():
    scene = ResolvedScene(objects=[])
    with pytest.raises(ValueError, match="unknown rule type"):
        run_rules(scene, [{"id": "x", "type": "not_a_real_check"}])


def test_violations_are_always_warnings():
    scene = ResolvedScene(
        objects=[
            _obj("zone", box(0, 0, 10, 10), rule="no_burnable_material"),
            _obj("deck", box(2, 2, 4, 4), material="deck"),
        ]
    )
    violations = run_rules(
        scene,
        [{"id": "r1", "type": "keepout_material_exclusion", "excluded_materials": ["deck"]}],
    )
    assert len(violations) == 1
    assert violations[0].severity == "warning"


def test_load_default_rules_file():
    rules = load_rules(DEFAULT_RULES)
    assert {r["id"] for r in rules} == {
        "no_burnable_in_firepit_keepout",
        "firepit_keepout_concentric",
        "firepit_keepout_contained_by_site",
        "no_unintended_overlaps",
        "shed_south_access_clearance",
    }


# --- keepout_material_exclusion ------------------------------------------


def test_material_exclusion_flags_overlap():
    scene = ResolvedScene(
        objects=[
            _obj("zone", box(0, 0, 10, 10), rule="no_burnable_material"),
            _obj("deck", box(5, 5, 15, 15), material="deck"),
        ]
    )
    violations = run_rules(
        scene, [{"id": "r1", "type": "keepout_material_exclusion", "excluded_materials": ["deck"]}]
    )
    assert len(violations) == 1
    assert violations[0].object_ids == ["zone", "deck"]


def test_material_exclusion_ignores_non_excluded_materials():
    scene = ResolvedScene(
        objects=[
            _obj("zone", box(0, 0, 10, 10), rule="no_burnable_material"),
            _obj("gravel", box(5, 5, 15, 15), material="gravel"),
        ]
    )
    violations = run_rules(
        scene, [{"id": "r1", "type": "keepout_material_exclusion", "excluded_materials": ["deck"]}]
    )
    assert violations == []


def test_material_exclusion_respects_zone_rule_filter():
    scene = ResolvedScene(
        objects=[
            _obj("zone_a", box(0, 0, 10, 10), rule="no_burnable_material"),
            _obj("zone_b", box(0, 0, 10, 10), rule="some_other_rule"),
            _obj("deck", box(0, 0, 10, 10), material="deck"),
        ]
    )
    violations = run_rules(
        scene,
        [
            {
                "id": "r1",
                "type": "keepout_material_exclusion",
                "zone_rule": "no_burnable_material",
                "excluded_materials": ["deck"],
            }
        ],
    )
    assert {v.object_ids[0] for v in violations} == {"zone_a"}


# --- concentricity --------------------------------------------------------


def test_concentricity_flags_drift():
    scene = ResolvedScene(
        objects=[
            _obj("firepit", box(0, 0, 2, 2)),  # centroid (1, 1)
            _obj("keepout", box(5, 5, 15, 15)),  # centroid (10, 10)
        ]
    )
    violations = run_rules(
        scene,
        [{"id": "r1", "type": "concentricity", "tolerance": 0.01, "pairs": [{"zone": "keepout", "center": "firepit"}]}],
    )
    assert len(violations) == 1


def test_concentricity_silent_within_tolerance():
    scene = ResolvedScene(
        objects=[
            _obj("firepit", box(0, 0, 2, 2)),
            _obj("keepout", box(-4, -4, 6, 6)),  # same centroid (1, 1)
        ]
    )
    violations = run_rules(
        scene,
        [{"id": "r1", "type": "concentricity", "tolerance": 0.01, "pairs": [{"zone": "keepout", "center": "firepit"}]}],
    )
    assert violations == []


# --- containment -----------------------------------------------------------


def test_containment_flags_escape():
    scene = ResolvedScene(
        objects=[
            _obj("parent", box(0, 0, 10, 10)),
            _obj("zone", box(5, 5, 20, 20)),
        ]
    )
    violations = run_rules(
        scene,
        [{"id": "r1", "type": "containment", "pairs": [{"zone": "zone", "parent": "parent"}]}],
    )
    assert len(violations) == 1
    assert "outside" in violations[0].message


def test_containment_silent_when_fully_inside():
    scene = ResolvedScene(
        objects=[
            _obj("parent", box(0, 0, 10, 10)),
            _obj("zone", box(2, 2, 8, 8)),
        ]
    )
    violations = run_rules(
        scene,
        [{"id": "r1", "type": "containment", "pairs": [{"zone": "zone", "parent": "parent"}]}],
    )
    assert violations == []


# --- no_overlap_unless_stacked --------------------------------------------


def test_overlap_flagged_by_default():
    scene = ResolvedScene(
        objects=[
            _obj("a", box(0, 0, 10, 10)),
            _obj("b", box(5, 5, 15, 15)),
        ]
    )
    violations = run_rules(scene, [{"id": "r1", "type": "no_overlap_unless_stacked"}])
    assert len(violations) == 1


def test_overlap_exception_pair_silenced():
    scene = ResolvedScene(
        objects=[
            _obj("a", box(0, 0, 10, 10)),
            _obj("b", box(5, 5, 15, 15)),
        ]
    )
    violations = run_rules(
        scene, [{"id": "r1", "type": "no_overlap_unless_stacked", "exceptions": [["b", "a"]]}]
    )
    assert violations == []


def test_overlap_ignores_annotation_objects():
    scene = ResolvedScene(
        objects=[
            _obj("a", box(0, 0, 10, 10)),
            _obj("marker", box(5, 5, 15, 15), annotation=True),
        ]
    )
    violations = run_rules(scene, [{"id": "r1", "type": "no_overlap_unless_stacked"}])
    assert violations == []


def test_overlap_ignores_ground_cover_materials():
    scene = ResolvedScene(
        objects=[
            _obj("ground", box(0, 0, 10, 10), material="lawn"),
            _obj("deck", box(5, 5, 15, 15), material="deck"),
        ]
    )
    violations = run_rules(
        scene, [{"id": "r1", "type": "no_overlap_unless_stacked", "ignore_materials": ["lawn"]}]
    )
    assert violations == []


# --- directional_clearance --------------------------------------------------


def test_clearance_flags_obstruction():
    scene = ResolvedScene(
        objects=[
            _obj("bay", box(0, 0, 4, 4)),
            _obj("fence", box(0, -2, 4, 0)),  # sits right in the south clearance zone
        ]
    )
    violations = run_rules(
        scene,
        [{"id": "r1", "type": "directional_clearance", "object": "bay", "direction": "south", "distance": 3}],
    )
    assert len(violations) == 1


def test_clearance_silent_when_clear():
    scene = ResolvedScene(objects=[_obj("bay", box(0, 0, 4, 4))])
    violations = run_rules(
        scene,
        [{"id": "r1", "type": "directional_clearance", "object": "bay", "direction": "south", "distance": 3}],
    )
    assert violations == []


def test_clearance_ignores_ground_cover():
    scene = ResolvedScene(
        objects=[
            _obj("bay", box(0, 0, 4, 4)),
            _obj("lawn", box(-10, -10, 20, 0), material="lawn"),
        ]
    )
    violations = run_rules(
        scene,
        [
            {
                "id": "r1",
                "type": "directional_clearance",
                "object": "bay",
                "direction": "south",
                "distance": 3,
                "ignore_materials": ["lawn"],
            }
        ],
    )
    assert violations == []


def test_clearance_rejects_unknown_direction():
    scene = ResolvedScene(objects=[_obj("bay", box(0, 0, 4, 4))])
    with pytest.raises(ValueError, match="unknown clearance direction"):
        run_rules(
            scene,
            [{"id": "r1", "type": "directional_clearance", "object": "bay", "direction": "up", "distance": 3}],
        )


# --- integration against the example scene --------------------------------


def test_default_rules_against_example_scene():
    doc = load_scene(EXAMPLE_SCENE)
    scene = resolve_scene(doc)
    rules = load_rules(DEFAULT_RULES)
    violations = run_rules(scene, rules)

    fired = {v.rule_id for v in violations}
    assert fired == {
        "no_burnable_in_firepit_keepout",
        "firepit_keepout_contained_by_site",
        "no_unintended_overlaps",
    }
    # the relation-based centering means this one should never fire
    assert "firepit_keepout_concentric" not in fired
    assert "shed_south_access_clearance" not in fired
