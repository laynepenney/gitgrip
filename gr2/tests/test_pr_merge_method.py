from __future__ import annotations

import json

import pytest
from gr2.python_cli import platform as platform_mod
from gr2.python_cli.pr import (
    MergeMethod,
    UnpermittedMergeMethodError,
    resolve_merge_method,
)


def test_explicit_method_precedes_configured_method() -> None:
    assert resolve_merge_method(explicit="rebase", configured="squash") is MergeMethod.REBASE


def test_configured_method_precedes_merge_commit_default() -> None:
    assert resolve_merge_method(configured="squash") is MergeMethod.SQUASH
    assert resolve_merge_method() is MergeMethod.MERGE


@pytest.mark.parametrize("bad", ["", "  ", "Squash", "fast-forward", "none"])
def test_unrecognised_method_refuses_instead_of_falling_back(bad: str) -> None:
    with pytest.raises(ValueError):
        resolve_merge_method(explicit=bad)


def test_permitted_and_unpermitted_methods_are_a_paired_control() -> None:
    assert (
        resolve_merge_method(explicit="squash", permitted=["merge", "squash"])
        is MergeMethod.SQUASH
    )
    with pytest.raises(UnpermittedMergeMethodError):
        resolve_merge_method(explicit="squash", permitted=["merge"])


@pytest.mark.parametrize(
    ("method", "flag"),
    [
        (MergeMethod.MERGE, "--merge"),
        (MergeMethod.SQUASH, "--squash"),
        (MergeMethod.REBASE, "--rebase"),
    ],
)
def test_resolved_method_reaches_gh_as_an_explicit_flag(
    monkeypatch: pytest.MonkeyPatch,
    method: MergeMethod,
    flag: str,
) -> None:
    recorded: list[list[str]] = []

    class _Proc:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(argv: list[str], **_kwargs: object) -> _Proc:
        recorded.append(list(argv))
        if argv[1:3] == ["pr", "merge"]:
            return _Proc("")
        return _Proc(
            json.dumps(
                {
                    "number": 42,
                    "url": "https://github.com/owner/repo/pull/42",
                    "state": "MERGED",
                    "mergeCommit": {"oid": "a" * 40},
                }
            )
        )

    monkeypatch.setattr(platform_mod.subprocess, "run", fake_run)

    platform_mod.GitHubAdapter().merge_pr("owner/repo", 42, method=method)

    assert flag in recorded[0]
    assert recorded[1][-1] == "number,url,state,mergeCommit"
