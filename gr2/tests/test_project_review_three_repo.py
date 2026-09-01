"""M1 local three-repository contract, deliberately landed before its service."""

from __future__ import annotations

import argparse
import subprocess
import dataclasses
from pathlib import Path

import pytest

from gr2.prototypes import lane_workspace_prototype as lanes


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _source(root: Path, name: str) -> tuple[Path, str, str]:
    origin = root / f"{name}.git"
    _git(root, "init", "--bare", "-b", "main", str(origin))
    source = root / name
    _git(root, "clone", "-q", str(origin), str(source))
    _git(source, "config", "user.email", "m1@example.invalid")
    _git(source, "config", "user.name", "m1")
    (source / "README.md").write_text(f"{name} base\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "base")
    _git(source, "push", "-q", "origin", "main")
    base = _git(source, "rev-parse", "main")
    branch = f"review/{name}"
    _git(source, "checkout", "-q", "-b", branch)
    (source / "review.txt").write_text(f"{name} review\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "review")
    _git(source, "push", "-q", "origin", branch)
    head = _git(source, "rev-parse", branch)
    _git(source, "checkout", "-q", "main")
    return source, base, head


def _world(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / ".grip").mkdir(parents=True)
    (workspace / ".grip" / "workspace_spec.toml").write_text('''schema_version = 1
workspace_name = "m1"

[[repos]]
name = "alpha"
path = "sources/alpha"
url = "https://example.invalid/alpha.git"

[[repos]]
name = "beta"
path = "sources/beta"
url = "https://example.invalid/beta.git"

[[repos]]
name = "gamma"
path = "sources/gamma"
url = "https://example.invalid/gamma.git"

[[units]]
name = "atlas"
path = "agents/atlas"
repos = ["alpha", "beta", "gamma"]
''')
    sources = {name: _source(tmp_path, name) for name in ("alpha", "beta", "gamma")}
    home = tmp_path / "home"
    _git(tmp_path, "init", "-q", str(home))
    _git(home, "config", "user.email", "m1@example.invalid")
    _git(home, "config", "user.name", "m1")
    (home / "tracked.txt").write_text("base\n")
    _git(home, "add", ".")
    _git(home, "commit", "-q", "-m", "home")
    (home / "tracked.txt").write_text("dirty\n")
    (home / "untracked.txt").write_text("keep\n")
    lanes.create_lane(argparse.Namespace(workspace_root=workspace, owner_unit="atlas", lane_name="home", type="feature", repos="alpha", branch="main", source="test", default_commands=[]))
    lanes.enter_lane(argparse.Namespace(workspace_root=workspace, owner_unit="atlas", lane_name="home", actor="agent:atlas", notify_channel=False, recall=False))
    current = lanes.current_lane_file(workspace, "atlas").read_bytes()
    return workspace, sources, home, current


def test_three_repo_exact_pins_open_only_after_all_members_verify(tmp_path: Path) -> None:
    workspace, sources, home, current = _world(tmp_path)
    from gr2.python_cli.project_review import ProjectReviewPin, make_spec, open_project_review
    pins = [ProjectReviewPin(key=name, repo=f"local:{source[0]}", path=f"repos/{name}", base=source[1], head=source[2]) for name, source in reversed(list(sources.items()))]
    from gr2.python_cli import grip
    grip.grip_init(workspace)
    spec = make_spec(workspace, pins)
    outcome = open_project_review(workspace=workspace, owner_unit="atlas", lane_name="review-m1", spec=spec, sources={name: (source[0], f"review/{name}") for name, source in sources.items()}, allow_local=True)
    assert outcome.status == "opened"
    assert [record.head for record in outcome.observed] == [sources[name][2] for name in ("alpha", "beta", "gamma")]
    assert all((outcome.review_root / "repos" / name / ".git").is_dir() for name in sources)
    assert home.joinpath("tracked.txt").read_text() == "dirty\n"
    assert home.joinpath("untracked.txt").read_text() == "keep\n"
    assert lanes.current_lane_file(workspace, "atlas").read_bytes() != current


def test_missing_pin_refuses_before_any_review_materialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, sources, _home, current = _world(tmp_path)
    from gr2.python_cli import grip, project_review
    grip.grip_init(workspace)
    pins = [project_review.ProjectReviewPin(name, f"local:{source[0]}", f"repos/{name}", source[1], ("f" * 40 if name == "gamma" else source[2])) for name, source in sources.items()]
    spec = project_review.make_spec(workspace, pins)
    calls: list[str] = []
    monkeypatch.setattr(project_review.review, "open_review_lane", lambda **kwargs: calls.append("clone"))
    outcome = project_review.open_project_review(workspace=workspace, owner_unit="atlas", lane_name="missing", spec=spec, sources={name: (source[0], f"review/{name}") for name, source in sources.items()}, allow_local=True)
    assert outcome.status == "refused" and outcome.failures[0].key == "gamma"
    assert calls == []
    assert lanes.current_lane_file(workspace, "atlas").read_bytes() == current


def test_beta_failure_is_partial_and_never_enters_review_lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, sources, _home, current = _world(tmp_path)
    from gr2.python_cli import grip, project_review
    grip.grip_init(workspace)
    spec = project_review.make_spec(workspace, [project_review.ProjectReviewPin(name, f"local:{source[0]}", f"repos/{name}", source[1], source[2]) for name, source in sources.items()])
    real = project_review.review.open_review_lane
    calls: list[str] = []
    def fail_beta(**kwargs):
        key = kwargs["lane_repo_root"].name
        calls.append(key)
        if key == "beta":
            raise RuntimeError("beta injected failure")
        return real(**kwargs)
    monkeypatch.setattr(project_review.review, "open_review_lane", fail_beta)
    outcome = project_review.open_project_review(workspace=workspace, owner_unit="atlas", lane_name="partial", spec=spec, sources={name: (source[0], f"review/{name}") for name, source in sources.items()}, allow_local=True)
    assert outcome.status == "partial" and calls == ["alpha", "beta"]
    assert [record.head for record in outcome.observed] == [sources["alpha"][2]]
    assert lanes.current_lane_file(workspace, "atlas").read_bytes() == current


@pytest.mark.parametrize("field,value", [("repo", "local:/substituted"), ("path", "repos/substituted"), ("base", "a" * 40), ("head", "b" * 40)])
def test_full_gr_commit_field_mismatch_refuses_before_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str) -> None:
    workspace, sources, _home, current = _world(tmp_path)
    from gr2.python_cli import grip, project_review
    grip.grip_init(workspace)
    pins = [project_review.ProjectReviewPin(name, f"local:{source[0]}", f"repos/{name}", source[1], source[2]) for name, source in sources.items()]
    spec = project_review.make_spec(workspace, pins)
    beta = next(pin for pin in spec.pins if pin.key == "beta")
    mismatched = dataclasses.replace(beta, **{field: value})
    bad_spec = dataclasses.replace(spec, pins=tuple(mismatched if pin.key == "beta" else pin for pin in spec.pins))
    calls: list[str] = []
    monkeypatch.setattr(project_review.review, "open_review_lane", lambda **_kwargs: calls.append("open"))
    outcome = project_review.open_project_review(workspace=workspace, owner_unit="atlas", lane_name="mismatch", spec=bad_spec, sources={name: (source[0], f"review/{name}") for name, source in sources.items()}, allow_local=True)
    assert outcome.status == "refused"
    assert outcome.failures[0].key == "beta" and field in outcome.failures[0].reason
    assert calls == []
    assert lanes.current_lane_file(workspace, "atlas").read_bytes() == current


def test_project_review_cli_adapter_and_structured_rendering_are_registered() -> None:
    from gr2.python_cli import app as app_module
    from gr2.python_cli import project_review
    commands = {command.name: command for command in app_module.review_app.registered_commands}
    assert "open-project" in commands
    outcome = project_review.ProjectReviewOutcome("refused", "a" * 40, (), (project_review.ProjectReviewFailure("beta", "mismatch for head"),), None, False)
    assert project_review.outcome_payload(outcome) == {"status": "refused", "grip_commit": "a" * 40, "observed": [], "failures": [{"key": "beta", "reason": "mismatch for head"}], "review_root": None, "current_lane_changed": False}
