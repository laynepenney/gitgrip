"""`review close-gr <lane-dir>`: a verb-owned teardown for an `open-gr --enter`
reconstruction lane (originating exit-point work tracked privately).

`open-gr --enter` is a pure reconstruction into `--lane-dir` — it pushes no lane
onto the return stack and changes no cwd, so `review exit-gr` (the open-PROJECT
pop, which needs OWNER_UNIT, a receipt, and a lane to pop) cannot apply and the
`--lane-dir` was left for a hand `rm`. This gives it a symmetric teardown: open-gr
writes a small marker, and `close-gr` reads it, refuses a directory that is NOT an
open-gr lane (so it never rm's an arbitrary path), and reclaims the tree.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from gr2.python_cli import app as gr2_app
from gr2.python_cli import open_gr_review


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _base_remote_and_range(tmp_path: Path) -> tuple[str, str, str, str]:
    """A bare origin whose main carries only BASE, plus a range.patch for a pre-push
    head. Returns (remote_url, base_sha, head_sha, range_patch_text)."""
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
    (work / "f.txt").write_text("base\nchange\n")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "head")
    head = _git(work, "rev-parse", "HEAD")
    range_patch = subprocess.run(
        ["git", "format-patch", f"{base}..{head}", "--stdout"],
        cwd=work, text=True, capture_output=True, check=True).stdout
    return str(origin), base, head, range_patch


def _open_gr_lane(tmp_path: Path, runner: CliRunner) -> tuple[Path, str]:
    """Bind a range and open-gr --enter into a lane. Returns (lane_dir, gr_sha)."""
    ws = tmp_path / "ws"
    (ws / ".grip").mkdir(parents=True)
    from gr2.python_cli import grip
    grip.grip_init(ws)
    remote, base, head, range_patch = _base_remote_and_range(tmp_path)
    range_file = tmp_path / "range.patch"
    range_file.write_text(range_patch)
    res = runner.invoke(gr2_app.app, [
        "review", "bind", str(ws), "--repo", "alpha", "--remote", remote,
        "--base", base, "--head", head, "--ref", "refs/heads/main",
        "--from-range", str(range_file),
    ])
    assert res.exit_code == 0, res.output
    gr_sha = res.output.strip()[len("gr:"):]
    lane_dir = tmp_path / "lane"
    res2 = runner.invoke(gr2_app.app, [
        "review", "open-gr", str(ws), gr_sha, "--repo", "alpha",
        "--lane-dir", str(lane_dir), "--enter",
    ])
    assert res2.exit_code == 0, res2.output
    return lane_dir, gr_sha


def test_open_gr_enter_writes_a_reconstruct_marker(tmp_path: Path) -> None:
    runner = CliRunner()
    lane_dir, gr_sha = _open_gr_lane(tmp_path, runner)
    marker = lane_dir / open_gr_review._OPEN_GR_MARKER
    assert marker.exists(), "open-gr --enter must write a teardown marker in the lane"
    data = json.loads(marker.read_text())
    assert data["kind"] == "open-gr-reconstruct"
    assert data["gr_commit"] == gr_sha


def test_close_gr_reclaims_the_lane(tmp_path: Path) -> None:
    runner = CliRunner()
    lane_dir, gr_sha = _open_gr_lane(tmp_path, runner)
    assert lane_dir.exists()
    res = runner.invoke(gr2_app.app, ["review", "close-gr", str(lane_dir)])
    assert res.exit_code == 0, res.output
    assert not lane_dir.exists(), "close-gr must reclaim the open-gr lane tree"
    assert gr_sha[:12] in res.output, res.output  # names the commit it reclaimed


def test_open_gr_enter_refuses_a_nonempty_lane_dir(tmp_path: Path) -> None:
    # Probe C (Stromus R2 v1, RAN): open-gr --enter into a PRE-EXISTING dir that holds
    # a foreign file must REFUSE, because close-gr reclaims the WHOLE --lane-dir. The
    # marker proves open-gr WROTE there, not that it CREATED the dir; without this guard
    # close-gr removes the foreign file. open-gr owns the lane or does not write it.
    runner = CliRunner()
    ws = tmp_path / "ws"
    (ws / ".grip").mkdir(parents=True)
    from gr2.python_cli import grip
    grip.grip_init(ws)
    remote, base, head, range_patch = _base_remote_and_range(tmp_path)
    range_file = tmp_path / "range.patch"
    range_file.write_text(range_patch)
    res = runner.invoke(gr2_app.app, [
        "review", "bind", str(ws), "--repo", "alpha", "--remote", remote,
        "--base", base, "--head", head, "--ref", "refs/heads/main",
        "--from-range", str(range_file),
    ])
    assert res.exit_code == 0, res.output
    gr_sha = res.output.strip()[len("gr:"):]

    # --repo OMITTED: root is the mkdir'd PARENT (each row -> root/<key>) and the
    # marker lands at root/. Without the guard open-gr writes the lane UNDER the
    # pre-existing foreign file, and close-gr then rmtrees the whole root.
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "foreign.txt").write_text("keep me\n")
    res2 = runner.invoke(gr2_app.app, [
        "review", "open-gr", str(ws), gr_sha,
        "--lane-dir", str(shared), "--enter",
    ])
    assert res2.exit_code != 0, res2.output
    assert (shared / "foreign.txt").exists(), "open-gr must not write into a non-empty dir"
    assert not (shared / open_gr_review._OPEN_GR_MARKER).exists(), "no marker written"
    # and with no marker, close-gr also refuses — the foreign file is doubly safe.
    res3 = runner.invoke(gr2_app.app, ["review", "close-gr", str(shared)])
    assert res3.exit_code != 0
    assert (shared / "foreign.txt").exists()


def test_close_gr_refuses_a_dir_without_the_marker(tmp_path: Path) -> None:
    # Safety: close-gr must never rm a directory that is not an open-gr lane.
    runner = CliRunner()
    plain = tmp_path / "not-a-lane"
    plain.mkdir()
    (plain / "keep.txt").write_text("do not delete me\n")
    res = runner.invoke(gr2_app.app, ["review", "close-gr", str(plain)])
    assert res.exit_code != 0
    assert plain.exists(), "close-gr must not remove a directory lacking the marker"
    assert (plain / "keep.txt").exists()
