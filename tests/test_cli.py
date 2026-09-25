from pathlib import Path

import pytest
from PIL import Image

from landscape.cli import build_parser, main

EXAMPLE_SCENE = Path(__file__).parent.parent / "scenes" / "example.yaml"
DEFAULT_MATERIALS = Path(__file__).parent.parent / "assets" / "materials.yaml"


def test_render_requires_out():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["render", "scene.yaml"])


def test_render_parses_expected_args():
    parser = build_parser()
    args = parser.parse_args(["render", "scene.yaml", "--mode", "flat", "--out", "out/plan.png"])
    assert args.command == "render"
    assert args.scene == "scene.yaml"
    assert args.mode == "flat"
    assert args.out == "out/plan.png"


def test_edit_parses_expected_args():
    parser = build_parser()
    args = parser.parse_args(["edit", "scene.yaml", "--materials", "custom.yaml", "--show-annotations"])
    assert args.command == "edit"
    assert args.scene == "scene.yaml"
    assert args.materials == "custom.yaml"
    assert args.show_annotations is True
    assert args.rules is None


def test_edit_parses_rules_arg():
    parser = build_parser()
    args = parser.parse_args(["edit", "scene.yaml", "--rules", "rules/backyard.yaml"])
    assert args.rules == "rules/backyard.yaml"


def test_art_mode_not_yet_implemented(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["render", str(EXAMPLE_SCENE), "--mode", "art", "--out", "out/plan.png"])
    assert exc_info.value.code == 1
    assert "not yet implemented" in capsys.readouterr().err


def test_unsupported_extension_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["render", str(EXAMPLE_SCENE), "--out", "out/plan.jpg", "--materials", str(DEFAULT_MATERIALS)])
    assert exc_info.value.code == 1
    assert "unsupported --out extension" in capsys.readouterr().err


def test_render_flat_end_to_end_png(tmp_path, capsys):
    out = tmp_path / "plan.png"
    exit_code = main(
        [
            "render",
            str(EXAMPLE_SCENE),
            "--mode",
            "flat",
            "--out",
            str(out),
            "--materials",
            str(DEFAULT_MATERIALS),
            "--legend",
            "--show-annotations",
        ]
    )
    assert exit_code == 0
    assert out.exists()
    with Image.open(out) as img:
        assert img.size[0] > 0 and img.size[1] > 0
    # a silent success looks indistinguishable from doing nothing at all
    assert str(out) in capsys.readouterr().out


def test_render_flat_end_to_end_svg(tmp_path):
    out = tmp_path / "nested" / "plan.svg"
    exit_code = main(
        ["render", str(EXAMPLE_SCENE), "--out", str(out), "--materials", str(DEFAULT_MATERIALS)]
    )
    assert exit_code == 0
    assert out.exists()  # --out's parent dir is created if missing
    assert "<svg" in out.read_text()


def test_render_png_at_a_given_dpi(tmp_path):
    out = tmp_path / "plan.png"
    exit_code = main(
        ["render", str(EXAMPLE_SCENE), "--out", str(out), "--materials", str(DEFAULT_MATERIALS), "--dpi", "150"]
    )
    assert exit_code == 0
    with Image.open(out) as img:
        assert round(img.info["dpi"][0]) == 150
        assert img.size[0] == round(40 * 36 / 72 * 150)  # example.yaml: 40 ft at 36 pt/ft
