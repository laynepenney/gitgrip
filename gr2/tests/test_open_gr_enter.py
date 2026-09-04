"""Project-tier open-gr --enter (R2 Exact Work Stream 2 step 4): one review-kind
gr commit opens one exact multi-repo review; exit restores the prior lane + cwd."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

import typer

from gr2.prototypes import lane_workspace_prototype as lanes
from gr2.python_cli import app as gr2_app
from gr2.python_cli import grip, open_gr_review, project_review


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _source(root: Path, name: str) -> tuple[Path, str, str]:
    """A source repo pushed to a bare origin: returns (source, base_sha, head_sha)."""
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
    (source / "review.txt").write_text(f"{name} review\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "review")
    _git(source, "push", "-q", "origin", f"review/{name}")
    head = _git(source, "rev-parse", f"review/{name}")
    _git(source, "checkout", "-q", "main")
    return source, base, head


def _world(tmp_path: Path):
    """workspace (grip-inited) + 3 sources + a HOME lane entered + a prior cwd."""
    workspace = tmp_path / "workspace"
    (workspace / ".grip").mkdir(parents=True)
    sources = {name: _source(tmp_path, name) for name in ("alpha", "beta", "gamma")}
    (workspace / ".grip" / "workspace_spec.toml").write_text(
        'schema_version = 1\nworkspace_name = "m1"\n\n'
        + "\n".join(
            f'[[repos]]\nname = "{name}"\npath = "sources/{name}"\n'
            f'url = "{_git(src[0], "remote", "get-url", "origin")}"\n'
            for name, src in sources.items()
        )
        + '\n[[units]]\nname = "atlas"\npath = "agents/atlas"\nrepos = ["alpha", "beta", "gamma"]\n'
    )
    grip.grip_init(workspace)
    prior_cwd = tmp_path / "home"
    prior_cwd.mkdir()
    lanes.create_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name="home", type="feature",
        repos="alpha", branch="main", source="test", default_commands=[],
    ))
    lanes.enter_lane(argparse.Namespace(
        workspace_root=workspace, owner_unit="atlas", lane_name="home",
        actor="agent:atlas", notify_channel=False, recall=False,
    ))
    return workspace, sources, prior_cwd


def _review_kind_commit(workspace: Path, sources: dict) -> tuple[str, dict]:
    pins = [
        project_review.ProjectReviewPin(
            key=name, repo=f"local:{src[0]}", path=f"repos/{name}", base=src[1], head=src[2]
        )
        for name, src in sources.items()
    ]
    spec = project_review.make_spec(workspace, pins)
    return spec.grip_commit, {name: (src[0], f"review/{name}") for name, src in sources.items()}


def test_open_gr_enter_materializes_pins_enters_and_writes_a_receipt(tmp_path: Path) -> None:
    workspace, sources, prior_cwd = _world(tmp_path)
    gr_commit, srcmap = _review_kind_commit(workspace, sources)
    before = lanes.current_lane_file(workspace, "atlas").read_bytes()

    outcome = open_gr_review.open_gr_enter(
        workspace, "atlas", "review-m1", gr_commit, srcmap,
        prior_cwd=prior_cwd, allow_local=True,
    )
    assert outcome.status == "opened"
    # the three pinned heads are materialized
    for name in sources:
        assert (outcome.review_root / "repos" / name / ".git").is_dir()
    # the agent is dropped into the review lane (current lane changed)
    assert lanes.current_lane_file(workspace, "atlas").read_bytes() != before
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "review-m1"
    # the receipt names the gr commit and the per-repo base/head
    import json
    receipt = json.loads(open_gr_review.open_gr_receipt_path(outcome.review_root).read_text())
    assert receipt["gr_commit"] == gr_commit
    assert receipt["prior_lane"] == "home"
    assert receipt["prior_cwd"] == str(prior_cwd)
    by_key = {r["key"]: r for r in receipt["repos"]}
    for name, src in sources.items():
        assert by_key[name]["base"] == src[1]
        assert by_key[name]["head"] == src[2]


def test_exit_restores_the_prior_lane_and_cwd(tmp_path: Path) -> None:
    workspace, sources, prior_cwd = _world(tmp_path)
    gr_commit, srcmap = _review_kind_commit(workspace, sources)
    outcome = open_gr_review.open_gr_enter(
        workspace, "atlas", "review-m1", gr_commit, srcmap, prior_cwd=prior_cwd, allow_local=True,
    )
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "review-m1"

    result = open_gr_review.exit_gr_review(workspace, "atlas", outcome.review_root, actor="agent:atlas")
    # the prior lane is restored and the prior cwd is returned
    assert result.restored_lane == "home"
    assert result.restored_cwd == str(prior_cwd)
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "home"


def test_open_gr_enter_refuses_a_non_review_kind_commit(tmp_path: Path) -> None:
    # Control 1: a workspace-kind commit is refused before any materialization.
    workspace, sources, prior_cwd = _world(tmp_path)
    wrong = grip.create_workspace_commit(workspace, [
        {"key": name, "remote": f"https://example.invalid/{name}.git", "path": f"repos/{name}",
         "commit": src[2], "base": src[1]}
        for name, src in sources.items()
    ])
    _, srcmap = _review_kind_commit(workspace, sources)
    with pytest.raises(grip.GripCorruptError):
        open_gr_review.open_gr_enter(
            workspace, "atlas", "review-m1", wrong, srcmap, prior_cwd=prior_cwd, allow_local=True,
        )
    # nothing was materialized and the agent stayed in home
    assert not (workspace / "reviews" / "atlas" / "review-m1").exists()
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "home"


def test_open_gr_enter_resolves_sources_from_the_recorded_remote(tmp_path: Path) -> None:
    # Step 6: no hand-passed transport map. open-gr resolves each source from the
    # pin's RECORDED REMOTE (pin.repo), clones the pinned head, and opens the same
    # exact review. This is the production shape -- the review-kind commit is the
    # only input.
    workspace, sources, prior_cwd = _world(tmp_path)
    gr_commit, _unused_srcmap = _review_kind_commit(workspace, sources)

    outcome = open_gr_review.open_gr_enter(
        workspace, "atlas", "review-m1", gr_commit, None,  # sources resolved from pins
        prior_cwd=prior_cwd, allow_local=True, staging_dir=tmp_path / "staging",
    )
    assert outcome.status == "opened"
    for name in sources:
        assert (outcome.review_root / "repos" / name / ".git").is_dir()
        # each materialized head equals the pinned head, reached via the recorded remote
        assert _git(outcome.review_root / "repos" / name, "rev-parse", "HEAD") == sources[name][2]
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "review-m1"


def test_resolve_sources_from_pins_refuses_a_remote_missing_the_head(tmp_path: Path) -> None:
    # Control: a recorded remote that does not carry the pinned head is refused at
    # resolve time, BEFORE any review lane opens; the agent stays in home.
    workspace, sources, prior_cwd = _world(tmp_path)
    pins = []
    for name, src in sources.items():
        head = src[2] if name != "beta" else "b" * 40  # beta's head is not on its remote
        pins.append(project_review.ProjectReviewPin(
            key=name, repo=f"local:{src[0]}", path=f"repos/{name}", base=src[1], head=head))
    gr_commit = project_review.make_spec(workspace, pins).grip_commit

    with pytest.raises(open_gr_review.OpenGrReviewError, match="does not carry head"):
        open_gr_review.open_gr_enter(
            workspace, "atlas", "review-m1", gr_commit, None,
            prior_cwd=prior_cwd, allow_local=True, staging_dir=tmp_path / "staging",
        )
    assert not (workspace / "reviews" / "atlas" / "review-m1").exists()
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "home"


def test_open_gr_enter_refuses_a_pin_head_missing_from_its_repo(tmp_path: Path) -> None:
    # Control 2: a pin whose head is not a commit in its source is refused BEFORE
    # any materialization (open_project_review preflights every pin).
    workspace, sources, prior_cwd = _world(tmp_path)
    pins = []
    for name, src in sources.items():
        head = src[2] if name != "beta" else "b" * 40  # beta's head does not exist
        pins.append(project_review.ProjectReviewPin(
            key=name, repo=f"local:{src[0]}", path=f"repos/{name}", base=src[1], head=head))
    gr_commit = project_review.make_spec(workspace, pins).grip_commit
    srcmap = {name: (src[0], f"review/{name}") for name, src in sources.items()}

    outcome = open_gr_review.open_gr_enter(
        workspace, "atlas", "review-m1", gr_commit, srcmap, prior_cwd=prior_cwd, allow_local=True,
    )
    assert outcome.status == "refused"
    assert not (workspace / "reviews" / "atlas" / "review-m1" / "repos").exists()
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "home"


# ---- Part 2: the CLI materialize verb (review open-project) routes through open_gr_enter ----

def _review_help(command_name: str) -> str:
    cmd = next(c for c in gr2_app.review_app.registered_commands if c.name == command_name)
    return (cmd.help or (cmd.callback.__doc__ or "")).strip()


def test_review_open_project_cli_materializes_from_recorded_remote_then_exits(tmp_path: Path) -> None:
    # One CLI invocation materializes the project-review-KIND commit's pinned heads
    # from their recorded remotes and enters the review lane; exit-gr restores.
    workspace, sources, prior_cwd = _world(tmp_path)
    gr_commit, _unused = _review_kind_commit(workspace, sources)

    gr2_app.review_open_project(
        workspace, gr_commit, "atlas", "review-m1",
        enter=True, sources_json=None, prior_cwd=prior_cwd, allow_local=True, json_output=False,
    )
    review_root = workspace / "reviews" / "atlas" / "review-m1"
    for name in sources:
        assert (review_root / "repos" / name / ".git").is_dir()
        assert _git(review_root / "repos" / name, "rev-parse", "HEAD") == sources[name][2]
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "review-m1"

    gr2_app.review_exit_gr(workspace, "atlas", review_root, actor="agent:atlas", json_output=False)
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "home"


def test_review_open_project_cli_refuses_non_review_kind_naming_the_kind(tmp_path: Path, capsys) -> None:
    # Control: a workspace-KIND commit is refused, and the refusal names the kind found.
    workspace, sources, prior_cwd = _world(tmp_path)
    wrong = grip.create_workspace_commit(workspace, [
        {"key": name, "remote": f"https://example.invalid/{name}.git", "path": f"repos/{name}",
         "commit": src[2], "base": src[1]}
        for name, src in sources.items()
    ])
    with pytest.raises(typer.Exit) as exc:
        gr2_app.review_open_project(
            workspace, wrong, "atlas", "review-m1",
            enter=True, sources_json=None, prior_cwd=prior_cwd, allow_local=True, json_output=False,
        )
    assert exc.value.exit_code == 2
    err = capsys.readouterr().err
    assert "gr2-workspace/v1" in err and "project review" in err
    assert not (workspace / "reviews" / "atlas" / "review-m1").exists()
    assert lanes.require_current_lane(workspace, "atlas")["lane_name"] == "home"


def test_review_open_project_requires_enter(tmp_path: Path) -> None:
    workspace, sources, prior_cwd = _world(tmp_path)
    gr_commit, _unused = _review_kind_commit(workspace, sources)
    with pytest.raises(typer.BadParameter):
        gr2_app.review_open_project(
            workspace, gr_commit, "atlas", "review-m1",
            enter=False, sources_json=None, prior_cwd=prior_cwd, allow_local=True, json_output=False,
        )


def test_both_review_verbs_help_names_commit_kind_and_path() -> None:
    op = _review_help("open-project")
    og = _review_help("open-gr")
    assert "MATERIALIZE" in op and "project-review-KIND" in op
    assert "RECONSTRUCT" in og and "review-BIND" in og
    # each verb points at the other so the fork is legible from --help alone
    assert "open-gr" in op and "open-project" in og
    assert "exit-gr" in _review_help("exit-gr").lower() or "exit" in _review_help("exit-gr").lower()
