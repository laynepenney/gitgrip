"""Contract: the id `grip log` prints is the id `grip checkout` accepts.

`.grip/snapshots/index.json` holds 40-character ids.  `grip log` prints the
first 12.  `_find_snapshot_by_id` required exact equality, so the ONLY
snapshot id a user can obtain from the CLI was the one that did not work:
`grip checkout` and `grip diff` answered `Snapshot not found` for an id
`grip log` had printed one command earlier, while the id that worked existed
solely inside a file nothing tells you to read.

Prefix resolution follows git's rule including the half that matters most: an
ambiguous prefix REFUSES rather than picking the first match.  Silently
resolving to one of several would make `checkout` land on an arbitrary
snapshot, which is worse than the refusal it replaces.
"""

from __future__ import annotations

import pytest
from gr2.python_cli.grip_cli import AmbiguousSnapshotId, _find_snapshot_by_id

FULL_A = "cb464d4a29f977eeb71d3f590beed4d8201be599"
FULL_B = "cb464d4a29f900000000000000000000deadbeef"  # shares a 12-char prefix
OTHER = "ff11ee22dd33cc44bb55aa6699887766554433221"

INDEX = [{"id": FULL_A, "message": "grip snapshot"}, {"id": OTHER, "message": "other"}]


def test_the_full_id_resolves():
    """The control. Without it, prefix resolution could be 'match anything'."""
    assert _find_snapshot_by_id(INDEX, FULL_A)["id"] == FULL_A


def test_the_twelve_char_id_that_grip_log_prints_resolves():
    """The defect itself: exactly what the user can see and type."""
    assert _find_snapshot_by_id(INDEX, FULL_A[:12])["id"] == FULL_A


def test_an_unknown_id_still_returns_none():
    """The refusal path must survive the widening. A resolver that started
    returning something for unknown input would be far worse than the bug."""
    assert _find_snapshot_by_id(INDEX, "deadbeefdead") is None


def test_an_ambiguous_prefix_raises_rather_than_picking_one():
    """The half of git's rule that is easy to skip, and the reason this is not
    simply `startswith`. Two snapshots share the 12-char prefix; resolving to
    the first would send `checkout` to an arbitrary one, silently."""
    index = [{"id": FULL_A}, {"id": FULL_B}]
    with pytest.raises(AmbiguousSnapshotId) as excinfo:
        _find_snapshot_by_id(index, FULL_A[:12])
    assert set(excinfo.value.matches) == {FULL_A, FULL_B}


def test_an_unambiguous_longer_prefix_still_resolves_when_a_shorter_one_is_ambiguous():
    """Ambiguity is a property of the prefix, not of the store: lengthening
    the prefix past the collision must work, or the refusal above would be a
    dead end with no way out."""
    index = [{"id": FULL_A}, {"id": FULL_B}]
    assert _find_snapshot_by_id(index, FULL_A[:20])["id"] == FULL_A


def test_an_empty_id_resolves_to_nothing():
    """`""` is a prefix of every id, so a naive `startswith` would call it
    ambiguous or return the first snapshot. Neither is acceptable."""
    assert _find_snapshot_by_id(INDEX, "") is None


# --- THROUGH THE VERB, not through the resolver ---------------------------
#
# Every test above calls ``_find_snapshot_by_id`` directly, and all six passed
# while an ambiguous prefix typed at the CLI still produced a traceback: the
# resolver RAISES and no verb caught it.  A witness that calls the guarded
# function proves the function; only a witness that travels the path a user
# travels proves the verb.  These invoke the real Typer app.

import json

from typer.testing import CliRunner

from gr2.python_cli.grip_cli import grip_app

_runner = CliRunner()

# Two real 40-character ids sharing their first 12 characters -- 12 because
# that is exactly what ``grip log`` prints, so this is the collision a user
# actually meets rather than a contrived one.
_SHARED = "abc123def456"
_ID_ONE = _SHARED + "0" * 28
_ID_TWO = _SHARED + "1" * 28


def _workspace_with_two_colliding_snapshots(tmp_path):
    snapshots = tmp_path / ".grip" / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "index.json").write_text(
        json.dumps(
            [
                {"id": _ID_ONE, "repo_states": {}},
                {"id": _ID_TWO, "repo_states": {}},
            ]
        )
    )
    return tmp_path


def _assert_clean_refusal(result):
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output, "a traceback reached the user"
    assert "AmbiguousSnapshotId" not in result.output
    # The candidates must be PRINTED. A bare "ambiguous" refusal leaves the
    # user with no way to proceed, which is barely better than the crash.
    assert _ID_ONE in result.output
    assert _ID_TWO in result.output


def test_checkout_refuses_an_ambiguous_prefix_without_a_traceback(tmp_path):
    ws = _workspace_with_two_colliding_snapshots(tmp_path)
    _assert_clean_refusal(_runner.invoke(grip_app, ["checkout", str(ws), _SHARED]))


def test_diff_refuses_an_ambiguous_prefix_without_a_traceback(tmp_path):
    ws = _workspace_with_two_colliding_snapshots(tmp_path)
    _assert_clean_refusal(_runner.invoke(grip_app, ["diff", str(ws), _SHARED, _ID_ONE]))


def test_the_verbs_still_resolve_an_unambiguous_prefix(tmp_path):
    """The control.  Without it the two above pass in a world where every
    prefix is refused, which would break the defect this range came to fix."""
    ws = _workspace_with_two_colliding_snapshots(tmp_path)
    result = _runner.invoke(grip_app, ["checkout", str(ws), _ID_ONE[:20]])
    assert "Ambiguous snapshot id" not in result.output
    assert "Traceback" not in result.output
