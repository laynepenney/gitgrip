"""G9: the durable record must survive the failure that produced it (grip#842).

The eight guarantees ported from gr1 all ask *is the claim true*. This one asks *does the
record survive the failure*, and it is a different axis. gr1 printed to a terminal; gr2
**emits events other programs read**, so a wrong guard misleads a reviewer while a wrong
event misleads a program.

The defect: `merge_pr_group` loops over PRs, merges repo A, fails on repo B, and raises.
`emit(PR_MERGED)` sits *after* the loop, so it never fires. The `merged` list is discarded
by the raise, and the error carried only the *failing* repo. **A is merged on the host and
nothing anywhere records it.** A caller cannot learn what already happened, and a retry
re-attempts A.

    Irreversible work that is not recorded is worse than work not done,
    because the next actor plans against a state that is false.

The fix is two layers that fail by DIFFERENT ROUTES, which is what makes them independent
rather than the same chance twice:

  - `PRMergeError` carries the completed list. In-process, structural; its failure mode is
    a raised exception. **This is what a retry must read.**
  - The event stays best-effort and durable. `emit` swallows every exception and returns
    `None` (see grip#843), so correctness must not rest on it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from python_cli.platform import AdapterError, PRRef  # noqa: E402
from python_cli.pr import (  # noqa: E402
    MergeMethod,
    PRMergeError,
    merge_pr_group,
)


class _FailAfter:
    """Merges successfully until `fail_on`, then raises -- the partial-failure case."""

    name = "github"

    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on
        self.merged: list[str] = []

    def merge_pr(self, repo: str, number: int, *, method: MergeMethod) -> PRRef:
        if repo == self.fail_on:
            raise AdapterError(f"simulated host refusal for {repo}")
        self.merged.append(repo)
        # `url` is ADAPTER-AUTHORED and appears nowhere in the group file, which is what
        # makes provenance observable. Without it, a completed list rebuilt from
        # `group["prs"]` and one carried back from the adapter are byte-identical, and
        # every assertion passes over either -- the values agree by coincidence because
        # the loop visits repos in group order.
        return PRRef(repo=repo, number=number, url=f"observed://{repo}/{number}")


def _group(workspace: Path, repos: list[str]) -> str:
    gid = "pg_test"
    d = workspace / ".grip" / "pr_groups"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{gid}.json").write_text(
        json.dumps(
            {
                "pr_group_id": gid,
                "owner_unit": "apollo",
                "lane_name": "lane",
                "prs": [{"repo": r, "pr_number": i + 1} for i, r in enumerate(repos)],
            }
        )
    )
    return gid


class TestTheErrorTypeMakesOmissionImpossible:
    """The completed list is a required constructor argument, with no default.

    An optional field will be omitted at exactly one call site within a year, and G9
    becomes a convention again. A required argument is not a reminder to think -- it is a
    refusal to construct. The type is the guarantee.
    """

    def test_completed_has_NO_DEFAULT_in_the_signature(self):
        """Asserts the signature, not a symptom -- caught by mutation, not by review.

        The first version of this test was `pytest.raises(TypeError)` on a call with the
        argument omitted. It survived the mutation that gives `completed` a default of
        `None`, because `list(None)` raises `TypeError` too. **The test passed for a
        different reason than the one it claimed**, and a green suite sat over exactly the
        defect it existed to prevent.

        A raised type is a symptom several mechanisms produce. The parameter having no
        default is the property itself, and nothing but the real thing satisfies it.
        """
        import inspect

        param = inspect.signature(PRMergeError.__init__).parameters["completed"]
        assert param.default is inspect.Parameter.empty, (
            f"`completed` has default {param.default!r}. A default makes G9 a convention: "
            f"one call site omits it, and the partial-merge record silently becomes empty "
            f"rather than absent -- which reads as 'nothing had merged'."
        )
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
            "`completed` must be keyword-only so it cannot be supplied positionally by "
            "accident, nor silently absorbed by a future signature change"
        )

    def test_an_EMPTY_completed_list_must_still_be_passed_explicitly(self):
        """Empty is a fact about the world, not an absence of information.

        "Nothing had merged when this failed" and "nobody recorded what merged" are
        different claims, and a default of `[]` would make them identical -- the same
        collapse as a guard reporting verified when it could not check.
        """
        err = PRMergeError("app", 1, "boom", completed=[])
        assert err.completed == []


class TestTheErrorCarriesWhatActuallyMerged:
    def test_partial_failure_reports_the_repos_that_DID_merge(self, tmp_path):
        gid = _group(tmp_path, ["app", "api", "web"])
        adapter = _FailAfter(fail_on="web")

        with pytest.raises(PRMergeError) as excinfo:
            merge_pr_group(
                workspace_root=tmp_path,
                pr_group_id=gid,
                adapter=adapter,
                actor="agent:apollo",
                method=MergeMethod.MERGE,
            )

        completed = [c["repo"] for c in excinfo.value.completed]
        assert completed == ["app", "api"], (
            "the error must name the irreversible work that already happened; a retry "
            "reading only the failing repo will merge app and api a second time"
        )

    def test_the_completed_list_matches_the_ADAPTER_not_the_group(self, tmp_path):
        """Evidence, not a token.

        Reconstructing the list from the group's own `prs` produces a plausible value that
        is right by construction and could never be wrong -- the same shape as
        `PRRef(repo=repo, number=number)` returning its own inputs.

        The first version of this test asserted only on `repo`, and it PASSED against a
        loop that appended `pr_info` straight from the group file. Both provenances
        produce the same repo names in the same order, because the loop visits repos in
        group order. **A value that agrees with the truth by coincidence passes every
        assertion the real one would**, and the test carried this name while proving
        nothing of the kind.

        So the assertion moved onto a field only the ADAPTER authors. `url` appears
        nowhere in the group file; a shortcut cannot fabricate it.
        """
        gid = _group(tmp_path, ["app", "api", "web"])
        adapter = _FailAfter(fail_on="api")

        with pytest.raises(PRMergeError) as excinfo:
            merge_pr_group(
                workspace_root=tmp_path,
                pr_group_id=gid,
                adapter=adapter,
                actor="agent:apollo",
                method=MergeMethod.MERGE,
            )

        completed = excinfo.value.completed
        assert [c["repo"] for c in completed] == adapter.merged == ["app"]
        assert [c.get("url") for c in completed] == ["observed://app/1"], (
            "the completed list was rebuilt from the group file rather than carried back "
            "from the adapter. It happens to name the right repos, and it is not evidence "
            "that anything merged -- the same list is produced by a loop that never "
            "consulted the host at all."
        )

    def test_failure_on_the_FIRST_repo_reports_an_empty_list_not_a_missing_one(self, tmp_path):
        gid = _group(tmp_path, ["app", "api"])

        with pytest.raises(PRMergeError) as excinfo:
            merge_pr_group(
                workspace_root=tmp_path,
                pr_group_id=gid,
                adapter=_FailAfter(fail_on="app"),
                actor="agent:apollo",
                method=MergeMethod.MERGE,
            )

        assert excinfo.value.completed == []


class TestTheTwoLayersAreIndependent:
    """Depth is only depth if the layers fail by different routes.

    A durable record that the in-process path depends on is the same chance twice. These
    tests exist because `emit` swallows every exception (grip#843): if correctness rested
    on it, G9 would be satisfied by a mechanism that can silently do nothing.
    """

    def test_a_durable_event_records_the_partial_merge(self, tmp_path):
        gid = _group(tmp_path, ["app", "api", "web"])

        with pytest.raises(PRMergeError):
            merge_pr_group(
                workspace_root=tmp_path,
                pr_group_id=gid,
                adapter=_FailAfter(fail_on="web"),
                actor="agent:apollo",
                method=MergeMethod.MERGE,
            )

        events = [
            json.loads(line)
            for f in tmp_path.rglob("*.jsonl")
            for line in f.read_text().splitlines()
            if line.strip()
        ]
        merged_records = [e for e in events if e.get("completed") or e.get("repos")]
        assert merged_records, (
            f"no event recorded the completed merges; events were "
            f"{[e.get('type') for e in events]}. The host state changed and the durable "
            f"log does not say so."
        )

    def test_the_exception_still_carries_the_list_when_EMIT_ITSELF_FAILS(
        self, tmp_path, monkeypatch
    ):
        """The independence claim, stated as the thing that must survive.

        If a broken event layer can take the in-process layer down with it, they were
        never two layers. Note this cannot happen today only because `emit` swallows
        everything -- which is exactly why it must not be the thing correctness rests on.
        """
        from python_cli import pr as pr_mod

        def _exploding_emit(**kwargs):
            raise RuntimeError("event subsystem is down")

        monkeypatch.setattr(pr_mod, "emit", _exploding_emit)
        gid = _group(tmp_path, ["app", "api", "web"])

        with pytest.raises(PRMergeError) as excinfo:
            merge_pr_group(
                workspace_root=tmp_path,
                pr_group_id=gid,
                adapter=_FailAfter(fail_on="web"),
                actor="agent:apollo",
                method=MergeMethod.MERGE,
            )

        assert [c["repo"] for c in excinfo.value.completed] == ["app", "api"], (
            "a failure in the best-effort layer must not erase the reliable one, and "
            "must not replace PRMergeError with the event layer's own exception"
        )
