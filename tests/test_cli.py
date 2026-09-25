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


def test_render_art_mode_end_to_end(tmp_path):
    out = tmp_path / "art.png"
    exit_code = main(
        ["render", str(EXAMPLE_SCENE), "--mode", "art", "--out", str(out), "--materials", str(DEFAULT_MATERIALS),
         "--dpi", "30", "--wash", "layered"]
    )
    assert exit_code == 0
    with Image.open(out) as img:
        assert img.size == (round(40 * 36 / 72 * 30),) * 2
        assert round(img.info["dpi"][0]) == 30


def test_render_art_mode_defaults_to_200_dpi(tmp_path, monkeypatch):
    """Without --dpi the CLI passes none, so each renderer's own default
    applies: 200 for art (checked here without paying for a 200 DPI render
    of the 40 ft example), 72 for flat PNG."""
    import inspect

    import landscape.cli as cli
    from landscape.render_art import render_art_to_pdf

    calls = []
    monkeypatch.setattr(cli, "render_to_file", lambda *a, **k: calls.append(k))
    main(["render", str(EXAMPLE_SCENE), "--mode", "art", "--out", str(tmp_path / "a.pdf"), "--materials", str(DEFAULT_MATERIALS)])

    assert "dpi" not in calls[0]
    assert inspect.signature(render_art_to_pdf).parameters["dpi"].default == 200


def test_unsupported_extension_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["render", str(EXAMPLE_SCENE), "--out", "out/plan.jpg", "--materials", str(DEFAULT_MATERIALS)])
    assert exc_info.value.code == 1
    assert "unsupported output type '.jpg'" in capsys.readouterr().err


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


def test_render_pdf_with_scale_bar_and_north_arrow(tmp_path):
    import pdfplumber

    from landscape.render_flat import DECORATION_STRIP_PT

    out = tmp_path / "plan.pdf"
    exit_code = main(
        [
            "render", str(EXAMPLE_SCENE), "--out", str(out), "--materials", str(DEFAULT_MATERIALS),
            "--scale-bar", "--north-arrow", "--north-angle", "15",
        ]
    )
    assert exit_code == 0
    with pdfplumber.open(out) as pdf:
        page = pdf.pages[0]
        assert page.height == 40 * 36 + DECORATION_STRIP_PT  # example.yaml: 40 ft at 36 pt/ft
        assert "1:24" in page.extract_text()
