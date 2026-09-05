"""Row 4 (R2 Exact Work Stream 2): run the reviewed repo's tests INSIDE the
materialized review lane and record it in the project-tier receipt as fruit.

`record_review_verification` runs a test command in `review_root/repos/<key>` and
appends a verification record binding the REAL exit code, the head the lane holds,
the lane cwd, and -- measured by a probe under the same interpreter -- which python
and which package file actually resolved there. The last two exist because a stale
editable install can silently import a DIFFERENT desk's package; a receipt that
cannot say whose code it tested has the same defect one layer up.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gr2.prototypes import lane_workspace_prototype as lanes
from gr2.python_cli import grip, open_gr_review, project_review


@pytest.fixture(autouse=True)
def _isolated_review_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPT_REVIEW_CACHE_ROOT", str(tmp_path / "review-cache"))
    monkeypatch.delenv("SYNAPT_REVIEW_PROFILE_DIR", raising=False)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _source_with_package(root: Path, name: str, *, package: bool) -> tuple[Path, str, str]:
    """A source repo whose review head optionally carries an importable package plus
    a trivial passing test. Returns (source, base_sha, head_sha)."""
    origin = root / f"{name}.git"
    _git(root, "init", "--bare", "-b", "main", str(origin))
    source = root / name
    _git(root, "clone", "-q", str(origin), str(source))
    _git(source, "config", "user.email", "t@example.invalid")
    _git(source, "config", "user.name", "t")
    (source / "README.md").write_text(f"{name} base\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "base")
    _git(source, "push", "-q", "origin", "main")
    base = _git(source, "rev-parse", "main")
    _git(source, "checkout", "-q", "-b", f"review/{name}")
    if package:
        pkg = source / f"{name}_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('WHERE = "lane"\n')
        (source / "test_smoke.py").write_text(
            f"import {name}_pkg\n\n\ndef test_where():\n    assert {name}_pkg.WHERE == \"lane\"\n"
        )
    (source / "review.txt").write_text(f"{name} review\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "review")
    _git(source, "push", "-q", "origin", f"review/{name}")
    head = _git(source, "rev-parse", f"review/{name}")
    _git(source, "checkout", "-q", "main")
    return source, base, head


def _open_single_repo_review(tmp_path: Path, name: str, *, package: bool):
    """Grip-init a one-repo workspace, make a review-kind gr commit, and open it.
    Returns (workspace, review_root, head_sha)."""
    import argparse

    workspace = tmp_path / "workspace"
    (workspace / ".grip").mkdir(parents=True)
    src, base, head = _source_with_package(tmp_path, name, package=package)
    url = _git(src, "remote", "get-url", "origin")
    (workspace / ".grip" / "workspace_spec.toml").write_text(
        f'schema_version = 1\nworkspace_name = "m1"\n\n'
        f'[[repos]]\nname = "{name}"\npath = "sources/{name}"\nurl = "{url}"\n'
        f'\n[[units]]\nname = "atlas"\npath = "agents/atlas"\nrepos = ["{name}"]\n'
    )
    grip.grip_init(workspace)
    prior_cwd = tmp_path / "home"
    prior_cwd.mkdir()
    lanes.create_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name="home", type="feature",
        repos=name, branch="main", source="test", default_commands=[],
    ))
    lanes.enter_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name="home",
        actor="agent:atlas", notify_channel=False, recall=False,
    ))
    pins = [project_review.ProjectReviewPin(
        key=name, repo=f"local:{src}", path=f"repos/{name}", base=base, head=head)]
    spec = project_review.make_spec(workspace, pins)
    outcome = open_gr_review.open_gr_enter(
        workspace, "atlas", "review-m1", spec.grip_commit,
        {name: (src, f"review/{name}")}, prior_cwd=prior_cwd, allow_local=True,
    )
    assert outcome.status == "opened", outcome
    return workspace, outcome.review_root, head


def test_verification_records_a_green_run_inside_the_lane(tmp_path: Path) -> None:
    # The e2e: open a review lane, run the repo's pytest INSIDE it, read the receipt
    # back. The record must bind exit 0, the reviewed head, a cwd inside the lane, the
    # interpreter, and a module_path that resolves to the LANE's package.
    _, review_root, head = _open_single_repo_review(tmp_path, "solo", package=True)

    record = open_gr_review.record_review_verification(
        review_root, "solo",
        command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts="],
        interpreter=sys.executable,
        import_module="solo_pkg",
    )
    assert record["exit_code"] == 0
    assert record["head_tested"] == head
    lane_dir = review_root / "repos" / "solo"
    # cwd is MEASURED (the probe's os.getcwd()), so compare resolved paths -- on macOS
    # the lane dir under /var/folders resolves through the /private symlink.
    assert Path(record["cwd"]).resolve() == lane_dir.resolve()
    # the probe ran under the interpreter we asked for
    assert Path(record["interpreter"]).resolve() == Path(sys.executable).resolve()
    # and the package it imported is the LANE's copy, not some other checkout's
    assert Path(record["module_path"]).resolve() == (lane_dir / "solo_pkg" / "__init__.py").resolve()

    # the record is persisted in the receipt's verification list
    receipt = json.loads(open_gr_review.open_gr_receipt_path(review_root).read_text())
    assert receipt["verification"][-1] == record


def test_verification_records_the_real_nonzero_exit(tmp_path: Path) -> None:
    # Mutant (b) witness: a command that really exits non-zero must be recorded as
    # non-zero. A "verification always green" implementation dies here.
    _, review_root, _ = _open_single_repo_review(tmp_path, "solo", package=True)
    record = open_gr_review.record_review_verification(
        review_root, "solo",
        command=[sys.executable, "-c", "import sys; sys.exit(3)"],
        interpreter=sys.executable,
        import_module="solo_pkg",
    )
    assert record["exit_code"] == 3


def test_module_path_reveals_an_out_of_lane_import(tmp_path: Path, monkeypatch) -> None:
    # Stromus's addition witness: when the reviewed lane does NOT contain the package
    # and a stale copy is on the interpreter's path, the receipt must EXPOSE that the
    # imported code lives outside the lane -- naming the foreign file, not silently
    # passing. Here the lane has no package; a shadow dir on PYTHONPATH does. Because
    # the shadow module is imported by ABSOLUTE name via PYTHONPATH (cwd holds no such
    # package), module_path points OUTSIDE the lane, which is exactly the defect a
    # reviewer needs the receipt to surface.
    _, review_root, _ = _open_single_repo_review(tmp_path, "bare", package=False)
    shadow = tmp_path / "desk-shadow"
    (shadow / "ghost_pkg").mkdir(parents=True)
    (shadow / "ghost_pkg" / "__init__.py").write_text('WHERE = "desk"\n')
    monkeypatch.setenv("PYTHONPATH", str(shadow))

    record = open_gr_review.record_review_verification(
        review_root, "bare",
        command=[sys.executable, "-c", "pass"],
        interpreter=sys.executable,
        import_module="ghost_pkg",
    )
    resolved = Path(record["module_path"]).resolve()
    assert resolved == (shadow / "ghost_pkg" / "__init__.py").resolve()
    # and it is NOT under the review lane -- the receipt names the foreign code
    assert (review_root / "repos" / "bare") not in resolved.parents


def test_verification_measures_the_cwd_where_the_command_ran(tmp_path: Path) -> None:
    # cwd witness: the test command drops a marker file into ITS OWN cwd. The marker
    # must land inside the lane dir, and the recorded cwd (MEASURED via the probe's
    # os.getcwd(), not copied from the request) must resolve to the lane dir. A record
    # that writes str(lane_dir) without measuring, or a lane_dir pointed elsewhere,
    # fails one or both.
    _, review_root, _ = _open_single_repo_review(tmp_path, "solo", package=True)
    lane_dir = review_root / "repos" / "solo"
    marker = "MARKER_ran_here.txt"
    record = open_gr_review.record_review_verification(
        review_root, "solo",
        command=[sys.executable, "-c", f"open({marker!r}, 'w').write('x')"],
        interpreter=sys.executable,
        import_module="solo_pkg",
    )
    assert (lane_dir / marker).exists(), "the command did not run inside the lane dir"
    assert Path(record["cwd"]).resolve() == lane_dir.resolve()


def test_head_tested_uses_reconstructed_head_when_present(tmp_path: Path) -> None:
    # reconstructed_head witness: for a carried-range pin the lane holds the
    # reconstructed head (a different sha than the pinned head). head_tested must be
    # the reconstructed one. A mutant that ignores reconstructed_head and reads
    # head only survives without this fixture.
    _, review_root, head = _open_single_repo_review(tmp_path, "solo", package=True)
    receipt_path = open_gr_review.open_gr_receipt_path(review_root)
    receipt = json.loads(receipt_path.read_text())
    fake_reconstructed = "0" * 40
    for row in receipt["repos"]:
        if row["key"] == "solo":
            row["reconstructed_head"] = fake_reconstructed
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")

    record = open_gr_review.record_review_verification(
        review_root, "solo",
        command=[sys.executable, "-c", "pass"],
        interpreter=sys.executable,
        import_module="solo_pkg",
    )
    assert record["head_tested"] == fake_reconstructed
    assert record["head_tested"] != head


def test_two_verifications_are_both_recorded(tmp_path: Path) -> None:
    # append witness: a second verification must NOT replace the first. A mutant that
    # assigns [record] instead of appending survives without a second call.
    _, review_root, _ = _open_single_repo_review(tmp_path, "solo", package=True)
    for _ in range(2):
        open_gr_review.record_review_verification(
            review_root, "solo",
            command=[sys.executable, "-c", "pass"],
            interpreter=sys.executable,
            import_module="solo_pkg",
        )
    receipt = json.loads(open_gr_review.open_gr_receipt_path(review_root).read_text())
    assert len(receipt["verification"]) == 2


def test_verification_refuses_when_the_lane_dir_is_missing(tmp_path: Path) -> None:
    # is_dir witness: if the materialized lane dir is gone, refuse rather than run a
    # command in the wrong place. A mutant dropping the is_dir check survives without this.
    _, review_root, _ = _open_single_repo_review(tmp_path, "solo", package=True)
    shutil.rmtree(review_root / "repos" / "solo")
    with pytest.raises(open_gr_review.OpenGrReviewError, match="materialized lane dir missing"):
        open_gr_review.record_review_verification(
            review_root, "solo",
            command=[sys.executable, "-c", "pass"],
            interpreter=sys.executable,
            import_module="solo_pkg",
        )


def test_verification_refuses_a_key_the_review_did_not_materialize(tmp_path: Path) -> None:
    _, review_root, _ = _open_single_repo_review(tmp_path, "solo", package=True)
    with pytest.raises(open_gr_review.OpenGrReviewError, match="not in the review receipt"):
        open_gr_review.record_review_verification(
            review_root, "nope",
            command=[sys.executable, "-c", "pass"],
            interpreter=sys.executable,
            import_module="solo_pkg",
        )
