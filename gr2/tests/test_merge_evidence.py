from __future__ import annotations

import json
from pathlib import Path

import pytest
from gr2.python_cli.platform import (
    GitHubAdapter,
    MergeEvidenceError,
    MergeMethod,
    MergeReceipt,
    PRRef,
)


def _fake_gh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> tuple[Path, Path]:
    binary = tmp_path / "gh"
    log = tmp_path / "argv.jsonl"
    binary.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["FAKE_GH_ARGV_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
if args[:2] == ["pr", "merge"]:
    if not any(flag in args for flag in ("--merge", "--squash", "--rebase")):
        print("an explicit merge method is required", file=sys.stderr)
        raise SystemExit(2)
    if os.environ.get("FAKE_GH_DELETE_AFTER_MERGE"):
        os.unlink(sys.argv[0])
    raise SystemExit(0)
if args[:2] == ["pr", "view"]:
    if os.environ.get("FAKE_GH_VIEW_FAIL"):
        print("receipt lookup unavailable", file=sys.stderr)
        raise SystemExit(4)
    print(os.environ["FAKE_GH_VIEW_PAYLOAD"])
    raise SystemExit(0)
print(f"unexpected argv: {args!r}", file=sys.stderr)
raise SystemExit(3)
"""
    )
    binary.chmod(0o755)
    monkeypatch.setenv("FAKE_GH_ARGV_LOG", str(log))
    monkeypatch.setenv("FAKE_GH_VIEW_PAYLOAD", json.dumps(payload))
    return binary, log


def _merged_payload(
    *,
    repo: str = "synapt-dev/widget",
    number: int = 41,
    commit_sha: str | None = "a" * 40,
) -> dict[str, object]:
    return {
        "number": number,
        "url": f"https://github.com/{repo}/pull/{number}",
        "state": "MERGED",
        "mergeCommit": None if commit_sha is None else {"oid": commit_sha},
    }


def _calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.parametrize(
    ("method", "flag"),
    [
        (MergeMethod.MERGE, "--merge"),
        (MergeMethod.SQUASH, "--squash"),
        (MergeMethod.REBASE, "--rebase"),
    ],
)
def test_merge_receipt_comes_from_the_structured_host_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: MergeMethod,
    flag: str,
) -> None:
    binary, log = _fake_gh(tmp_path, monkeypatch, _merged_payload())

    receipt = GitHubAdapter(str(binary)).merge_pr(
        "synapt-dev/widget",
        41,
        method=method,
    )

    assert receipt == MergeReceipt(
        requested=PRRef(repo="synapt-dev/widget", number=41),
        observed=PRRef(
            repo="synapt-dev/widget",
            number=41,
            url="https://github.com/synapt-dev/widget/pull/41",
        ),
        commit_sha="a" * 40,
        requested_method=method,
    )
    assert _calls(log) == [
        ["pr", "merge", "41", "--repo", "synapt-dev/widget", flag],
        [
            "pr",
            "view",
            "41",
            "--repo",
            "synapt-dev/widget",
            "--json",
            "number,url,state,mergeCommit",
        ],
    ]


def test_host_explicitly_omitting_the_commit_is_not_reported_as_a_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary, _ = _fake_gh(
        tmp_path,
        monkeypatch,
        _merged_payload(commit_sha=None),
    )

    receipt = GitHubAdapter(str(binary)).merge_pr(
        "synapt-dev/widget",
        41,
        method=MergeMethod.MERGE,
    )

    assert receipt.commit_sha is None


def test_acknowledged_merge_with_unavailable_receipt_is_not_reported_as_merge_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary, _ = _fake_gh(tmp_path, monkeypatch, _merged_payload())
    monkeypatch.setenv("FAKE_GH_VIEW_FAIL", "1")

    with pytest.raises(MergeEvidenceError) as raised:
        GitHubAdapter(str(binary)).merge_pr(
            "synapt-dev/widget",
            41,
            method=MergeMethod.MERGE,
        )

    assert raised.value.requested == PRRef(repo="synapt-dev/widget", number=41)
    assert raised.value.requested_method is MergeMethod.MERGE
    assert raised.value.operation_acknowledged is True
    assert "receipt lookup unavailable" in str(raised.value)


def test_acknowledged_merge_with_receipt_process_launch_failure_is_outcome_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary, _ = _fake_gh(tmp_path, monkeypatch, _merged_payload())
    monkeypatch.setenv("FAKE_GH_DELETE_AFTER_MERGE", "1")

    with pytest.raises(MergeEvidenceError) as raised:
        GitHubAdapter(str(binary)).merge_pr(
            "synapt-dev/widget",
            41,
            method=MergeMethod.MERGE,
        )

    assert raised.value.requested == PRRef(repo="synapt-dev/widget", number=41)
    assert raised.value.requested_method is MergeMethod.MERGE
    assert raised.value.operation_acknowledged is True
    assert "receipt" in str(raised.value)


def test_receipt_url_with_query_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _merged_payload()
    payload["url"] = f"{payload['url']}?x=1"
    binary, _ = _fake_gh(tmp_path, monkeypatch, payload)

    with pytest.raises(MergeEvidenceError):
        GitHubAdapter(str(binary)).merge_pr(
            "synapt-dev/widget",
            41,
            method=MergeMethod.MERGE,
        )


def test_receipt_url_with_fragment_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _merged_payload()
    payload["url"] = f"{payload['url']}#frag"
    binary, _ = _fake_gh(tmp_path, monkeypatch, payload)

    with pytest.raises(MergeEvidenceError):
        GitHubAdapter(str(binary)).merge_pr(
            "synapt-dev/widget",
            41,
            method=MergeMethod.MERGE,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {**_merged_payload(), "state": "OPEN"},
        {**_merged_payload(), "number": 42},
        {
            **_merged_payload(),
            "url": "https://github.com/another-org/widget/pull/41",
        },
        {
            **_merged_payload(),
            "url": "https://evil.example/synapt-dev/widget/pull/41",
        },
        {**_merged_payload(), "url": "https://[broken/pull/41"},
        {**_merged_payload(), "mergeCommit": {}},
        {**_merged_payload(), "mergeCommit": {"oid": "not-an-object-id"}},
    ],
)
def test_malformed_or_mismatched_host_evidence_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    binary, _ = _fake_gh(tmp_path, monkeypatch, payload)

    with pytest.raises(MergeEvidenceError):
        GitHubAdapter(str(binary)).merge_pr(
            "synapt-dev/widget",
            41,
            method=MergeMethod.MERGE,
        )


def test_merge_receipt_is_not_a_success_boolean() -> None:
    assert "merged" not in MergeReceipt.__dataclass_fields__
