"""Export recipes (M7 batch export): one YAML file listing several
outputs of one scene, rendered in a single run by `landscape export`."""

from pathlib import Path

import pdfplumber
import pytest
from PIL import Image

from landscape.cli import main
from landscape.export_recipe import RecipeError, load_recipe, run_recipe
from landscape.render_flat import DECORATION_STRIP_PT

REPO = Path(__file__).parent.parent
EXAMPLE_SCENE = REPO / "scenes" / "example.yaml"  # 40 x 40 ft at 36 pt/ft
DEFAULT_MATERIALS = REPO / "assets" / "materials.yaml"


def _write_recipe(tmp_path: Path, body: str) -> Path:
    """A recipe in `tmp_path`, with `scene`/`materials` pointing at the
    repo's example scene — given as absolute paths so each test's `out:`
    entries stay relative to `tmp_path` (the recipe's own folder)."""
    recipe = tmp_path / "exports.yaml"
    recipe.write_text(f"scene: {EXAMPLE_SCENE}\nmaterials: {DEFAULT_MATERIALS}\n{body}")
    return recipe


def test_one_run_writes_every_output_with_its_own_options(tmp_path):
    recipe = _write_recipe(
        tmp_path,
        """
outputs:
  - out: plan.pdf
    scale_bar: true
    north_arrow: true
  - out: plan.png
    dpi: 150
  - out: plan.svg
""",
    )

    written = run_recipe(load_recipe(recipe))

    assert written == [tmp_path / "plan.pdf", tmp_path / "plan.png", tmp_path / "plan.svg"]
    with pdfplumber.open(tmp_path / "plan.pdf") as pdf:
        assert pdf.pages[0].height == 40 * 36 + DECORATION_STRIP_PT
    with Image.open(tmp_path / "plan.png") as img:
        assert round(img.info["dpi"][0]) == 150
        assert img.size == (round(40 * 36 / 72 * 150),) * 2  # no strip: this output didn't ask for one
    assert (tmp_path / "plan.svg").read_text().count("<svg") == 1


def test_paths_are_relative_to_the_recipe_file_not_the_working_directory(tmp_path, monkeypatch):
    """So a recipe keeps working wherever it's run from."""
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()
    recipe = _write_recipe(recipe_dir, "outputs:\n  - out: ../out/plan.png\n")
    monkeypatch.chdir(REPO)

    run_recipe(load_recipe(recipe))

    assert (tmp_path / "out" / "plan.png").exists()  # output folder created as needed


def test_defaults_apply_to_every_output_and_outputs_can_override_them(tmp_path):
    recipe = _write_recipe(
        tmp_path,
        """
defaults:
  scale_bar: true
  dpi: 100
outputs:
  - out: a.png
  - out: b.png
    scale_bar: false
""",
    )

    run_recipe(load_recipe(recipe))

    with Image.open(tmp_path / "a.png") as a, Image.open(tmp_path / "b.png") as b:
        assert a.size[1] == round((40 * 36 + DECORATION_STRIP_PT) * 100 / 72)
        assert b.size[1] == round(40 * 36 * 100 / 72)
        assert round(b.info["dpi"][0]) == 100


def test_a_default_dpi_is_ignored_for_vector_outputs(tmp_path):
    """`dpi` in `defaults` is a convenience for the PNGs; it mustn't make
    every SVG/PDF in the same recipe an error."""
    recipe = _write_recipe(tmp_path, "defaults:\n  dpi: 300\noutputs:\n  - out: plan.pdf\n")

    run_recipe(load_recipe(recipe))

    assert (tmp_path / "plan.pdf").read_bytes()[:4] == b"%PDF"


@pytest.mark.parametrize(
    "outputs, message",
    [
        ("  - out: plan.jpg\n", "unsupported"),
        ("  - out: plan.pdf\n    dpi: 300\n", "dpi only applies to .png"),
        ("  - out: plan.png\n    colour: red\n", "unknown option 'colour'"),
        ("  - dpi: 300\n", "'out' is required"),
        ("  - out: plan.png\n    mode: art\n", "art mode is not implemented yet"),
        ("  - out: plan.png\n    mode: sketch\n", "mode must be"),
        ("  - out: plan.png\n    legend: maybe\n", "legend must be true or false"),
        ("  - out: plan.png\n    dpi: lots\n", "dpi must be a number"),
    ],
)
def test_bad_outputs_are_reported_with_their_line(tmp_path, outputs, message):
    recipe = _write_recipe(tmp_path, "outputs:\n" + outputs)

    with pytest.raises(RecipeError, match=message) as excinfo:
        load_recipe(recipe)

    assert "exports.yaml, line 4" in str(excinfo.value)  # the output's own line (scene + materials + outputs: are 1-3)


def test_nothing_is_written_if_any_output_is_invalid(tmp_path):
    """Check the whole recipe before rendering anything, so a typo in the
    last output doesn't leave a half-finished batch behind."""
    recipe = _write_recipe(tmp_path, "outputs:\n  - out: good.png\n  - out: bad.jpg\n")

    with pytest.raises(RecipeError):
        run_recipe(load_recipe(recipe))

    assert not (tmp_path / "good.png").exists()


def test_a_recipe_needs_a_scene_and_at_least_one_output(tmp_path):
    no_scene = tmp_path / "a.yaml"
    no_scene.write_text("outputs:\n  - out: plan.png\n")
    no_outputs = _write_recipe(tmp_path, "outputs: []\n")

    with pytest.raises(RecipeError, match="'scene' is required"):
        load_recipe(no_scene)
    with pytest.raises(RecipeError, match="at least one output"):
        load_recipe(no_outputs)


def test_cli_export_runs_a_recipe(tmp_path, capsys):
    recipe = _write_recipe(tmp_path, "outputs:\n  - out: plan.png\n  - out: plan.svg\n")

    assert main(["export", str(recipe)]) == 0

    printed = capsys.readouterr().out
    assert "plan.png" in printed and "plan.svg" in printed
    assert (tmp_path / "plan.png").exists() and (tmp_path / "plan.svg").exists()


def test_cli_export_reports_recipe_errors_cleanly(tmp_path, capsys):
    recipe = _write_recipe(tmp_path, "outputs:\n  - out: plan.jpg\n")

    with pytest.raises(SystemExit) as excinfo:
        main(["export", str(recipe)])

    assert excinfo.value.code == 1
    assert "line 4" in capsys.readouterr().err


def test_the_shipped_backyard_recipe_is_valid():
    """The example recipe in the repo must stay loadable as the scene and
    options evolve."""
    recipe = load_recipe(REPO / "exports" / "backyard.yaml")
    assert recipe.outputs
