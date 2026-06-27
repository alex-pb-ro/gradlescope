"""Tests for the command-line interface."""
import json
import os

import pytest

from gradlescope import cli


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path)
    _write(os.path.join(root, "settings.gradle"), "include ':app'\ninclude ':core'\n")
    _write(
        os.path.join(root, "app", "build.gradle"),
        "plugins { id 'java' }\ndependencies { implementation project(':core')\n"
        " implementation 'g:a:1.+' }\n",
    )
    _write(os.path.join(root, "app", "src", "main", "java", "A.java"), "class A{}")
    _write(os.path.join(root, "core", "build.gradle"), "plugins { id 'java-library' }\n")
    return root


def test_scan_writes_json(repo, tmp_path, capsys):
    out = str(tmp_path / "r.json")
    code = cli.main(["scan", "--root", repo, "--json", out])
    assert code == 0
    captured = capsys.readouterr().out
    assert "Modules: 2" in captured
    assert json.load(open(out))["tool"] == "gradlescope"


def test_score_table(repo, capsys):
    code = cli.main(["score", "--root", repo])
    assert code == 0
    assert "Overall:" in capsys.readouterr().out


def test_score_fail_under(repo):
    assert cli.main(["score", "--root", repo, "--fail-under", "101"]) == 1
    assert cli.main(["score", "--root", repo, "--fail-under", "0"]) == 0


def test_report_md_stdout(repo, capsys):
    cli.main(["report", "--root", repo, "--format", "md"])
    assert "# gradlescope report" in capsys.readouterr().out


def test_report_ai_to_file(repo, tmp_path, capsys):
    out = str(tmp_path / "ai.md")
    cli.main(["report", "--root", repo, "--format", "ai", "--out", out])
    assert "```json" in open(out).read()


def test_report_json_format(repo, capsys):
    cli.main(["report", "--root", repo, "--format", "json"])
    assert json.loads(capsys.readouterr().out)["tool"] == "gradlescope"


def test_dashboard_writes_site(repo, tmp_path, capsys):
    out = str(tmp_path / "site")
    code = cli.main(["dashboard", "--root", repo, "--out", out])
    assert code == 0
    assert os.path.isfile(os.path.join(out, "index.html"))
    assert os.path.isfile(os.path.join(out, "history.json"))
    # Running twice should accumulate history for the trend.
    cli.main(["dashboard", "--root", repo, "--out", out])
    assert len(json.load(open(os.path.join(out, "history.json")))) == 2


def test_affected_lines(repo, capsys):
    cli.main(["affected", "--root", repo, "--file", "core/src/main/java/C.java", "--format", "lines"])
    out = capsys.readouterr().out.split()
    # changing :core affects :core and its dependent :app
    assert set(out) == {":app", ":core"}


def test_affected_json(repo, capsys):
    cli.main(["affected", "--root", repo, "--file", "app/src/main/java/A.java", "--format", "json"])
    assert json.loads(capsys.readouterr().out) == [":app"]


def test_serve_dispatch(repo, monkeypatch, capsys):
    called = {}

    def fake_serve(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(cli, "_serve", fake_serve)
    code = cli.main(["serve", "--root", repo, "--port", "9999"])
    assert code == 0
    assert called["port"] == 9999
    assert called["host"] == "127.0.0.1"


def test_config_override(repo, tmp_path, capsys):
    cfg = str(tmp_path / "cfg.json")
    with open(cfg, "w") as fh:
        json.dump({"min_gradle_major": 99}, fh)
    cli.main(["score", "--root", repo, "--config", cfg])
    # Just ensure it runs cleanly with a config file.
    assert "Overall:" in capsys.readouterr().out


def test_prompt_for_rule(repo, capsys):
    # :app declares a dynamic version -> dynamic-versions finding exists
    code = cli.main(["prompt", "--root", repo, "--rule", "dynamic-versions", "--module", ":app"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Goal" in out and "dynamic-versions" in out and ":app" in out


def test_prompt_list(repo, capsys):
    code = cli.main(["prompt", "--root", repo, "--list"])
    assert code == 0
    assert "@" in capsys.readouterr().out  # finding keys printed


def test_prompt_no_match(repo, capsys):
    code = cli.main(["prompt", "--root", repo, "--rule", "no-such-rule"])
    assert code == 1


def test_prompt_requires_rule(repo, capsys):
    code = cli.main(["prompt", "--root", repo])
    assert code == 2


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "gradlescope" in capsys.readouterr().out


def test_no_command_errors(capsys):
    with pytest.raises(SystemExit):
        cli.main([])
