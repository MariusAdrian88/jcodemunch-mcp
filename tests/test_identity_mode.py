"""Tests for local-first index identity mode selection."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from jcodemunch_mcp import config as config_module
from jcodemunch_mcp.storage import IndexStore
from jcodemunch_mcp.storage import git_root


def _git(*args, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _set_origin(path: Path, url: str) -> None:
    _git("remote", "add", "origin", url, cwd=path)


def test_default_config_for_hosted_clone_is_local_without_git_subprocess(tmp_path, monkeypatch):
    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")
    monkeypatch.setattr(
        config_module,
        "get",
        lambda key, default=None, repo=None: None if key == "identity_mode" else False if key == "git_root_identity" else default,
    )

    store = IndexStore(base_path=str(tmp_path / "store"))
    with patch.object(git_root.subprocess, "run", side_effect=AssertionError("git subprocess fired")):
        decision = git_root.resolve_index_identity(str(repo), mode="config", store=store)

    assert decision.mode == "local"
    assert decision.owner == "local"
    assert decision.name.startswith("kibana-clone-")
    assert decision.git_root == ""
    assert decision.walk_root == str(repo.resolve())


def test_explicit_git_mode_uses_origin_identity(tmp_path):
    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")

    decision = git_root.resolve_index_identity(
        str(repo),
        mode="git",
        store=IndexStore(base_path=str(tmp_path / "store")),
    )

    assert decision.mode == "git"
    assert decision.owner == "elastic"
    assert decision.name == "kibana"
    assert decision.git_root == str(repo.resolve())
    assert decision.walk_root == str(repo.resolve())


def test_existing_git_index_is_preserved_in_config_mode(tmp_path):
    from jcodemunch_mcp.tools.index_folder import index_folder

    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")
    (repo / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

    store_path = tmp_path / "store"
    first = index_folder(
        str(repo),
        use_ai_summaries=False,
        storage_path=str(store_path),
        context_providers=False,
        identity_mode="git",
    )
    assert first["success"] is True
    assert first["repo"] == "elastic/kibana"

    decision = git_root.resolve_index_identity(
        str(repo),
        mode="config",
        store=IndexStore(base_path=str(store_path)),
    )

    assert decision.mode == "git"
    assert decision.owner == "elastic"
    assert decision.name == "kibana"


def test_config_template_exposes_git_identity_opt_in():
    template = config_module.generate_template()

    assert '// "identity_mode": "git",' in template
    assert "Uncomment and set to \"git\" to opt in" in template
    assert '// "git_root_identity": true,' in template


def test_watcher_and_resolve_repo_delegate_to_identity_resolver(tmp_path):
    from jcodemunch_mcp.tools.resolve_repo import _compute_repo_id
    from jcodemunch_mcp.watcher import _local_repo_id

    project = tmp_path / "project"
    project.mkdir()
    store = IndexStore(base_path=str(tmp_path / "store"))
    decision = git_root.resolve_index_identity(str(project), mode="config", store=store)
    expected = f"{decision.owner}/{decision.name}"

    assert _compute_repo_id(project, store=store) == expected
    assert _local_repo_id(str(project), store=store) == expected
