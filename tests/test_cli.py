import pytest

from landscape.cli import build_parser, main


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


def test_render_not_yet_implemented(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["render", "scene.yaml", "--out", "out/plan.png"])
    assert exc_info.value.code == 1
    assert "not yet implemented" in capsys.readouterr().err
