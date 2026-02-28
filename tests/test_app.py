"""Tests for the app entry point CLI argument parsing."""

from shannon.app import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.config == "config.yaml"
    assert args.dangerously_skip_permissions is False


def test_parse_args_custom_config():
    args = parse_args(["--config", "my_config.yaml"])
    assert args.config == "my_config.yaml"


def test_parse_args_skip_permissions():
    args = parse_args(["--dangerously-skip-permissions"])
    assert args.dangerously_skip_permissions is True


def test_parse_args_speech():
    args = parse_args(["--speech"])
    assert args.speech is True


def test_parse_args_speech_default():
    args = parse_args([])
    assert args.speech is False


def test_parse_args_verbose():
    args = parse_args(["--verbose"])
    assert args.verbose is True


def test_parse_args_verbose_short():
    args = parse_args(["-v"])
    assert args.verbose is True


def test_parse_args_verbose_default():
    args = parse_args([])
    assert args.verbose is False


def test_parse_args_all_flags():
    args = parse_args([
        "--config", "custom.yaml",
        "--dangerously-skip-permissions",
        "--speech",
        "--verbose",
    ])
    assert args.config == "custom.yaml"
    assert args.dangerously_skip_permissions is True
    assert args.speech is True
    assert args.verbose is True
