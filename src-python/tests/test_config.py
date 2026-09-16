"""Tests for CLI arg parsing (token resolution)."""

import pytest

from app.core.config import parse_args


def test_token_flag_wins(monkeypatch, capsys):
    monkeypatch.setenv("SIDECAR_TOKEN", "envtoken")
    args = parse_args(["--token", "flagtoken"])
    assert args.token == "flagtoken"
    assert "generated ephemeral token" not in capsys.readouterr().err


def test_token_env_fallback(monkeypatch, capsys):
    monkeypatch.setenv("SIDECAR_TOKEN", "envtoken")
    args = parse_args([])
    assert args.token == "envtoken"
    assert "generated ephemeral token" not in capsys.readouterr().err


def test_token_generated_and_printed_when_missing(monkeypatch, capsys):
    monkeypatch.delenv("SIDECAR_TOKEN", raising=False)
    args = parse_args([])
    assert args.token
    err = capsys.readouterr().err
    # The token VALUE must never reach stderr (diagnostics leak surface).
    assert "generated an ephemeral token" in err
    assert args.token not in err


def test_port_defaults_to_zero_and_parses_int():
    assert parse_args([]).port == 0
    assert parse_args(["--port", "8080"]).port == 8080


def test_malformed_port_exits_with_usage_error(capsys):
    # argparse rejects non-int --port with SystemExit(2): a clean CLI usage
    # error, not a mystery timeout waiting on a bad bind in Rust.
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--port", "abc"])
    assert exc_info.value.code == 2
