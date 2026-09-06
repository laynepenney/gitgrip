"""`review bind --from-range`: a classic freeze-public-range.sh range.patch (the
pre-push head exists in NO clone the caller keeps and on NO remote, only as the
patch bytes) can be bound directly, WITHOUT a hand `git am` and WITHOUT an author
`--source` clone that holds the head.

The producer (`review bind`) owns the reconstruction: it derives the head-tree by
applying the range over base in a throwaway clone (grip._carry_objects_from_range,
the primitive the project tier already uses), carries the range in the object, and
`open-gr` reconstructs by `git am` and asserts TREE equality. This is the frozen-range
git-am exit point removed from the gr2 review producer (the R2 closing-fruit lane).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gr2.python_cli import app as gr2_app
from gr2.python_cli import grip


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _base_remote_and_range(tmp_path: Path) -> tuple[str, str, str, str, str]:
    """A bare origin whose `main` carries only BASE, plus a range.patch for a PRE-PUSH
    head that exists in no kept clone and on no remote. Returns
    (remote_url, base_sha, head_sha, head_tree, range_patch_text)."""
    origin = tmp_path / "alpha.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "config", "user.email", "a@e.invalid")
    _git(work, "config", "user.name", "a")
    (work / "f.txt").write_text("base\n")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "push", "-q", "origin", "main")
    base = _git(work, "rev-parse", "HEAD")
    (work / "f.txt").write_text("base\nreview change\n")
    (work / "new.txt").write_text("added by the review\n")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "review head")
    head = _git(work, "rev-parse", "HEAD")
    head_tree = _git(work, "rev-parse", "HEAD^{tree}")
    range_patch = subprocess.run(
        ["git", "format-patch", f"{base}..{head}", "--stdout"],
        cwd=work, text=True, capture_output=True, check=True).stdout
    return str(origin), base, head, head_tree, range_patch


def _init_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / ".grip").mkdir(parents=True)
    grip.grip_init(ws)
    return ws


def test_bind_from_range_carries_the_range_and_reconstructs_the_tree(tmp_path: Path) -> None:
    ws = _init_ws(tmp_path)
    remote, base, head, head_tree, range_patch = _base_remote_and_range(tmp_path)

    commit = grip.create_review_bind_commit(
        ws,
        [{"key": "alpha", "remote": remote, "path": "repos/alpha",
          "base": base, "head": head, "ref": "refs/heads/main",
          "range_patch": range_patch}],
    )
    # WITNESS (kills the routing mutation): a range-bearing row carries the objects
    # subtree, exactly as a --source row does. Neuter the `elif range_patch` branch
    # in create_review_bind_commit and this key is absent.
    assert "alpha" in grip._tree_keys(ws, commit, "objects")

    lane_dir = tmp_path / "lane" / "alpha"
    result = grip.reconstruct_review_lane(ws, commit, "alpha", lane_dir)
    # git am re-stamps the committer, so the sha differs; the TREE is the contract.
    assert result["reconstructed_tree"] == head_tree
    assert result["bound_head"] == head
    assert (lane_dir / "new.txt").read_text() == "added by the review\n"


def test_cli_bind_from_range_then_open_gr_matches_tree(tmp_path: Path) -> None:
    ws = _init_ws(tmp_path)
    remote, base, head, head_tree, range_patch = _base_remote_and_range(tmp_path)
    range_file = tmp_path / "range.patch"
    range_file.write_text(range_patch)
    runner = CliRunner()

    res = runner.invoke(gr2_app.app, [
        "review", "bind", str(ws), "--repo", "alpha", "--remote", remote,
        "--base", base, "--head", head, "--ref", "refs/heads/main",
        "--from-range", str(range_file),
    ])
    assert res.exit_code == 0, res.output
    assert res.output.strip().startswith("gr:"), res.output
    sha = res.output.strip()[len("gr:"):]

    lane_dir = tmp_path / "lane"
    res2 = runner.invoke(gr2_app.app, [
        "review", "open-gr", str(ws), sha, "--repo", "alpha",
        "--lane-dir", str(lane_dir), "--enter", "--json",
    ])
    assert res2.exit_code == 0, res2.output
    assert head_tree in res2.output, res2.output  # reconstructed_tree == bound_head_tree
    assert (lane_dir / "new.txt").read_text() == "added by the review\n"


def test_bind_from_range_refuses_a_head_the_range_does_not_describe(tmp_path: Path) -> None:
    # Head defense (parity with --source's source_missing_head): the declared --head
    # must be the head the range was formatted from. A different 40-hex head that is
    # NOT on the remote (so it clears the head-already-on-remote refusal) must still
    # be refused HERE, because the object records --head and open-gr reports it.
    ws = _init_ws(tmp_path)
    remote, base, _head, _tree, range_patch = _base_remote_and_range(tmp_path)
    wrong_head = "d" * 40  # valid sha shape, not on the remote, not the range's From-head
    with pytest.raises(grip.GripReviewRefused, match="range_head_mismatch"):
        grip.create_review_bind_commit(
            ws,
            [{"key": "alpha", "remote": remote, "path": "repos/alpha",
              "base": base, "head": wrong_head, "ref": "refs/heads/main",
              "range_patch": range_patch}],
        )


def test_bind_from_range_refuses_a_range_with_no_from_header(tmp_path: Path) -> None:
    ws = _init_ws(tmp_path)
    remote, base, head, _tree, _range_patch = _base_remote_and_range(tmp_path)
    with pytest.raises(grip.GripReviewRefused, match="range_no_from_header"):
        grip.create_review_bind_commit(
            ws,
            [{"key": "alpha", "remote": remote, "path": "repos/alpha",
              "base": base, "head": head, "ref": "refs/heads/main",
              "range_patch": "this carries no From <sha> header\n"}],
        )


def test_source_and_range_are_mutually_exclusive_in_the_row(tmp_path: Path) -> None:
    ws = _init_ws(tmp_path)
    remote, base, head, _tree, range_patch = _base_remote_and_range(tmp_path)
    with pytest.raises(grip.GripCorruptError, match="mutually exclusive"):
        grip.create_review_bind_commit(
            ws,
            [{"key": "alpha", "remote": remote, "path": "repos/alpha",
              "base": base, "head": head, "ref": "refs/heads/main",
              "source": str(tmp_path / "work"), "range_patch": range_patch}],
        )


def test_cli_source_and_from_range_are_mutually_exclusive(tmp_path: Path) -> None:
    ws = _init_ws(tmp_path)
    remote, base, head, _tree, range_patch = _base_remote_and_range(tmp_path)
    range_file = tmp_path / "range.patch"
    range_file.write_text(range_patch)
    runner = CliRunner()
    res = runner.invoke(gr2_app.app, [
        "review", "bind", str(ws), "--repo", "alpha", "--remote", remote,
        "--base", base, "--head", head, "--ref", "refs/heads/main",
        "--source", str(tmp_path / "work"), "--from-range", str(range_file),
    ])
    assert res.exit_code != 0
    assert "mutually exclusive" in res.output
