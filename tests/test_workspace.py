"""Tests for the per-repo workspace under the user's home dir."""
import os

from gradlescope import cli, workspace


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_home_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GRADLESCOPE_HOME", str(tmp_path / "home"))
    assert workspace.gradlescope_home() == str(tmp_path / "home")


def test_repo_slug_is_safe_and_stable():
    s1 = workspace.repo_slug("/a/b/my repo!")
    s2 = workspace.repo_slug("/a/b/my repo!")
    assert s1 == s2
    assert "/" not in s1 and " " not in s1 and "!" not in s1


def test_default_site_dir_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("GRADLESCOPE_HOME", str(tmp_path / "home"))
    d = workspace.default_site_dir("/some/repo")
    assert d.startswith(str(tmp_path / "home"))
    assert d.endswith("site")


def test_serve_uses_repo_workspace_root(monkeypatch, tmp_path):
    monkeypatch.setenv("GRADLESCOPE_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    _write(str(repo / "settings.gradle"), "include ':a'\n")
    _write(str(repo / "a" / "build.gradle"), "plugins { id 'java' }\n")
    captured = {}
    monkeypatch.setattr(cli, "_serve", lambda **kw: captured.update(kw))
    cli.main(["serve", "--root", str(repo)])
    assert captured["output_dir"] == workspace.repo_workspace(str(repo))
    assert "repos" in captured["output_dir"] and not captured["output_dir"].endswith("site")


def test_dashboard_tolerates_nonlist_history(monkeypatch, tmp_path):
    monkeypatch.setenv("GRADLESCOPE_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    _write(str(repo / "settings.gradle"), "include ':a'\n")
    _write(str(repo / "a" / "build.gradle"), "plugins { id 'java' }\n")
    ws = workspace.repo_workspace(str(repo))
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "history.json"), "w") as fh:
        fh.write('{"not": "a list"}')
    assert cli.main(["dashboard", "--root", str(repo)]) == 0
    import json

    hist = json.load(open(os.path.join(ws, "history.json")))
    assert isinstance(hist, list) and len(hist) == 1


def test_dashboard_writes_to_home_not_repo(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("GRADLESCOPE_HOME", str(home))
    repo = tmp_path / "repo"
    _write(str(repo / "settings.gradle"), "include ':app'\n")
    _write(str(repo / "app" / "build.gradle"), "plugins { id 'java' }\n")

    code = cli.main(["dashboard", "--root", str(repo)])
    assert code == 0
    # Output landed in the home workspace, not inside the analyzed repo.
    site_index = os.path.join(workspace.default_site_dir(str(repo)), "index.html")
    assert os.path.isfile(site_index)
    assert not os.path.exists(repo / ".gradlescope")
    # The repo gained no stray output files.
    assert set(os.listdir(repo)) == {"settings.gradle", "app"}
