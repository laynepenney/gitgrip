"""CLI glue over the review gr-commit engine: ``gr2 review bind|open-gr|verify``.

The engine functions (create_review_bind_commit / reconstruct_review_lane /
verify_review_commit) are covered by test_review_bind_verify and
test_review_open_lane. These tests cover the NEW thin Typer verbs, and the one
property those tests cannot see: that the glue turns an engine refusal or
corruption into a clean nonzero EXIT with real error text on stderr — never a
Python traceback, and never a swallowed exit 0. Glue is exactly where a caught
exception becomes a silent success, so every adversarial case asserts BOTH the
nonzero exit AND the absence of "Traceback" in the output.

Fathom's three antagonist probes (m_b2708f8f) map here: base-not-on-remote is
probe 3 (refuse at bind), tampered-range is probe 2 (open-gr must fail loud),
verify-on-tampered is probe 1/2 (verify recomputes, does not trust the record).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from gr2.python_cli import grip
from gr2.python_cli.app import app

runner = CliRunner()

TITLE = "feat: prove the review gr tree\n"
BODY = "body line\n"


def _env() -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": os.environ.get("PATH", ""),
    }


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=_env(), capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _fixture_repo(tmp_path: Path, name: str = "r") -> tuple[str, str, str, Path]:
    """A bare remote advertising dev@BASE, plus a work clone carrying an
    unpublished HEAD (a genuine pre-push review). Returns
    (remote_url, base, head, work_dir)."""
    work = tmp_path / f"{name}-work"
    _git(tmp_path, "init", "-b", "dev", str(work))
    (work / "f.txt").write_text("base\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "base")
    base = _git(work, "rev-parse", "HEAD")
    remote = tmp_path / f"{name}-origin.git"
    _git(tmp_path, "clone", "--bare", "--quiet", str(work), str(remote))
    (work / "f.txt").write_text("head under review\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "feat: the reviewed change")
    head = _git(work, "rev-parse", "HEAD")
    return str(remote), base, head, work


def _grip_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    grip.grip_init(ws)
    return ws


def _bind(ws: Path, remote: str, base: str, head: str, work: Path, key: str = "recall") -> str:
    result = runner.invoke(
        app,
        ["review", "bind", str(ws), "--repo", key, "--remote", remote,
         "--base", base, "--head", head, "--ref", "refs/heads/dev",
         "--path", key, "--source", str(work), "--title", TITLE, "--body", BODY],
    )
    assert result.exit_code == 0, result.output
    line = result.stdout.strip()
    assert line.startswith("gr:"), result.output
    return line


def _tamper_blob(ws: Path, commit_ref: str, tree_path: str, content: bytes) -> str:
    """Hand-craft a tampered review artifact: replace one carried blob and commit
    the mutated tree onto a NEW commit in .grip. Returns the new gr:<sha>."""
    gd = ws / ".grip"
    sha = commit_ref[3:] if commit_ref.startswith("gr:") else commit_ref
    blob = subprocess.run(
        ["git", "-C", str(gd), "hash-object", "-w", "--stdin"],
        input=content, env=_env(), capture_output=True, check=True,
    ).stdout.decode().strip()
    index = ws / ".tamper-index"
    env = {**_env(), "GIT_INDEX_FILE": str(index)}
    subprocess.run(["git", "-C", str(gd), "read-tree", sha], env=env, check=True)
    subprocess.run(
        ["git", "-C", str(gd), "update-index", "--add", "--cacheinfo",
         f"100644,{blob},{tree_path}"],
        env=env, check=True,
    )
    new_tree = subprocess.run(
        ["git", "-C", str(gd), "write-tree"], env=env, capture_output=True, text=True, check=True
    ).stdout.strip()
    new_commit = subprocess.run(
        ["git", "-C", str(gd), "commit-tree", new_tree, "-p", sha, "-m", "tamper"],
        env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    index.unlink(missing_ok=True)
    return f"gr:{new_commit}"


# --- happy path: the smallest proof, as a test -----------------------------


def test_bind_open_gr_verify_roundtrip(tmp_path):
    remote, base, head, work = _fixture_repo(tmp_path)
    ws = _grip_ws(tmp_path)
    grc = _bind(ws, remote, base, head, work)

    lane = tmp_path / "lane"
    opened = runner.invoke(
        app, ["review", "open-gr", str(ws), grc, "--repo", "recall",
               "--lane-dir", str(lane), "--enter", "--json"],
    )
    assert opened.exit_code == 0, opened.output
    assert (lane / "f.txt").read_text() == "head under review\n"
    # The assertion is on the TREE (git am mints a new head sha), so tree must match.
    assert _git(lane, "rev-parse", "HEAD^{tree}") == \
        _git(ws / ".grip", "show", f"{grc[3:]}:objects/recall/head-tree")

    verified = runner.invoke(app, ["review", "verify", str(ws), grc, "--json"])
    assert verified.exit_code == 0, verified.output
    assert '"tree_matches": true' in verified.stdout
    assert f'"observed_remote_head": "{base}"' in verified.stdout


def _multi_row(key, remote, base, head, work):
    return {"key": key, "remote": remote, "path": key, "head": head,
            "base": base, "ref": "refs/heads/dev", "title": TITLE,
            "body": BODY, "source": str(work)}


def test_open_gr_materializes_every_row_of_a_multi_row_commit(tmp_path):
    r1, b1, h1, w1 = _fixture_repo(tmp_path, "one")
    r2, b2, h2, w2 = _fixture_repo(tmp_path, "two")
    ws = _grip_ws(tmp_path)
    # A GENUINE two-row review commit. The CLI `bind` writes one row per commit,
    # so a multi-row commit is built through the engine directly -- expressing a
    # multi-row commit from the CLI surface is a named M1 follow-up. open-gr's
    # no-`--repo` path is what consumes it, and that path is what this witnesses.
    commit = grip.create_review_bind_commit(
        ws, [_multi_row("one", r1, b1, h1, w1), _multi_row("two", r2, b2, h2, w2)]
    )
    assert grip.review_row_keys(ws, commit) == ["one", "two"]  # one commit, two rows

    lane = tmp_path / "multilane"
    opened = runner.invoke(
        app, ["review", "open-gr", str(ws), f"gr:{commit}", "--lane-dir", str(lane), "--enter"],
    )
    assert opened.exit_code == 0, opened.output
    assert "one:" in opened.stdout and "two:" in opened.stdout
    assert opened.stdout.count("tree_match=True") == 2   # every bound row reconstructed
    assert (lane / "one" / "f.txt").read_text() == "head under review\n"
    assert (lane / "two" / "f.txt").read_text() == "head under review\n"


# --- Fathom probe 3: BASE NOT ON THE REMOTE, refuse at bind, cleanly -------


def test_bind_refuses_base_not_on_remote_with_clean_exit(tmp_path):
    remote, base, head, work = _fixture_repo(tmp_path)
    # An unrelated repo's sha: valid hex, never on this remote.
    other = tmp_path / "other"
    _git(tmp_path, "init", "-b", "dev", str(other))
    (other / "x").write_text("x\n")
    _git(other, "add", ".")
    _git(other, "commit", "-m", "unrelated")
    stranger = _git(other, "rev-parse", "HEAD")

    result = runner.invoke(
        app,
        ["review", "bind", str(ws := _grip_ws(tmp_path)), "--repo", "recall",
         "--remote", remote, "--base", stranger, "--head", head, "--ref", "refs/heads/dev",
         "--path", "recall", "--source", str(work), "--title", TITLE, "--body", BODY],
    )
    assert result.exit_code == 2, result.output
    assert "refused:" in result.output
    assert "Traceback" not in result.output  # clean error text, not a stack trace


# --- Fathom probe 2: TAMPERED CARRIED RANGE, open-gr must fail loud --------


def test_open_gr_propagates_tampered_range_loudly(tmp_path):
    remote, base, head, work = _fixture_repo(tmp_path)
    ws = _grip_ws(tmp_path)
    grc = _bind(ws, remote, base, head, work)
    tampered = _tamper_blob(ws, grc, "objects/recall/range.patch", b"not a valid patch\n")

    lane = tmp_path / "lane-tampered"
    opened = runner.invoke(
        app, ["review", "open-gr", str(ws), tampered, "--repo", "recall",
               "--lane-dir", str(lane), "--enter"],
    )
    assert opened.exit_code == 2, opened.output       # loud, not swallowed
    assert "refused:" in opened.output
    assert "Traceback" not in opened.output


# --- Fathom probe 1: WRONG HEAD, caught at open-gr by the head-TREE assertion.
# The bound head-tree is the only cryptographically pinned content: reconstruction
# ams the carried range and asserts the resulting tree equals objects/<key>/head-tree.
# Substituting the head-tree makes that assertion fail loud. (A tampered range,
# probe 2 above, fails the same assertion; the recorded commit-SHA and base-SHA are
# pinned instead at BIND time by the liveness refusal, not re-checked here.)


def test_open_gr_refuses_when_head_tree_is_wrong(tmp_path):
    remote, base, head, work = _fixture_repo(tmp_path)
    ws = _grip_ws(tmp_path)
    grc = _bind(ws, remote, base, head, work)
    # Claim a different head-tree than the range reconstructs to.
    wrong = _tamper_blob(
        ws, grc, "objects/recall/head-tree",
        b"0000000000000000000000000000000000000000\n",
    )
    lane = tmp_path / "lane-wronghead"
    opened = runner.invoke(
        app, ["review", "open-gr", str(ws), wrong, "--repo", "recall",
               "--lane-dir", str(lane), "--enter"],
    )
    assert opened.exit_code == 2, opened.output       # tree_mismatch, loud
    assert "refused:" in opened.output
    assert "Traceback" not in opened.output


# --- verify's own contract: STRUCTURAL integrity (recompute the canonical tree
# and compare ids). It catches an extraneous/missing file, a wrong schema, or a
# malformed row -- not a well-placed content swap, which verify faithfully
# re-encodes. Content trust lives at bind (liveness) and open-gr (reconstruction).


def test_verify_flags_structural_corruption_nonzero(tmp_path):
    remote, base, head, work = _fixture_repo(tmp_path)
    ws = _grip_ws(tmp_path)
    grc = _bind(ws, remote, base, head, work)
    # Add an extraneous blob the canonical recomputation will not reproduce.
    corrupt = _tamper_blob(ws, grc, "objects/recall/EXTRA", b"unexpected\n")

    verified = runner.invoke(app, ["review", "verify", str(ws), corrupt, "--json"])
    assert verified.exit_code != 0, verified.output   # structural drift is never green
    assert "Traceback" not in verified.output
    assert '"tree_matches": false' in verified.stdout
