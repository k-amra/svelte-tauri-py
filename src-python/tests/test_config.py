"""Tests for CLI arg parsing (token resolution)."""

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
    assert "generated ephemeral token" in err
    assert args.token in err
