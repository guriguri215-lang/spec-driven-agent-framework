from pathlib import Path

import pytest
from scripts.audit_repository import audit, candidate_files
from scripts.check_workspace_boundary import (
    check_boundary,
    is_link_or_reparse,
    resolve_workspace_parent,
)


def test_publication_audit_accepts_small_english_tree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# English\n", encoding="utf-8")

    assert candidate_files(root) == (root / "README.md",)
    assert audit(root, tmp_path) == ()
    assert not is_link_or_reparse(root)


def test_publication_audit_rejects_license_cjk_path_and_secret(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "LICENSE").write_text("pending", encoding="utf-8")
    (root / "bad.md").write_text(
        "\u65e5\u672c\u8a9e "
        + "C:\\"
        + "Users\\person\\file "
        + "ghp_"
        + ("a" * 26)
        + "\n",
        encoding="utf-8",
    )

    errors = audit(root, tmp_path)

    assert any("LICENSE" in error for error in errors)
    assert any("CJK" in error for error in errors)
    assert any("personal absolute path" in error for error in errors)
    assert any("possible secret" in error for error in errors)


def test_publication_audit_rejects_parent_git_and_large_file(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    (root / "large.txt").write_text("a" * 1_000_001, encoding="utf-8")

    errors = audit(root, tmp_path)

    assert any("parent workspace" in error for error in errors)
    assert any("size limit" in error for error in errors)


def test_publication_audit_scans_lock_files_and_path_variants(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "requirements.lock").write_text(
        "source = 'c:/"
        + "users/person/cache'\n",
        encoding="utf-8",
    )

    errors = audit(root, tmp_path)

    assert any("personal absolute path" in error for error in errors)


def test_boundary_check_requires_repository_git(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    errors = check_boundary(root, tmp_path)

    assert "The repository must contain .git." in errors


def test_boundary_default_parent_is_based_on_resolved_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)

    assert resolve_workspace_parent(Path("."), None) == tmp_path.resolve()
