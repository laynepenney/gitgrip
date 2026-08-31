"""Contract: `lane lease show` must not crash on a missing ``json`` attribute.

The CLI command built a ``SimpleNamespace`` without ``json`` while
``show_lane_leases`` reads ``args.json`` -- ``AttributeError:
'types.SimpleNamespace' object has no attribute 'json'``, a traceback in front
of the user for the most ordinary invocation there is. The sibling command
``review requirements`` right below it passes ``json=json_output``; this one
omitted it, and the verb had no ``--json`` option at all.

The witness invokes the CLI, which builds the deficient namespace -- calling
``show_lane_leases`` directly with a complete namespace would pass while the
shipped verb crashes (a witness that calls the callee pins the callee, not its
use).
"""

from __future__ import annotations

import json

import typer
from gr2.python_cli.app import lane_app
from typer.testing import CliRunner

app = typer.Typer()
app.add_typer(lane_app, name="lane")
runner = CliRunner()


def test_lease_show_does_not_crash_when_no_json_flag(tmp_path):
    """The production path: no leases, no ``--json``. Must render the table,
    not raise. Before the fix this surfaced ``AttributeError('json')``."""
    result = runner.invoke(app, ["lane", "lease", "show", str(tmp_path), "default", "somelane"])
    assert result.exit_code == 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "ACTOR" in result.output  # the human-readable table header


def test_lease_show_json_flag_emits_valid_json(tmp_path):
    """The ``--json`` path the missing attribute was meant to feed. Before the
    fix the option did not exist (exit 2); after, it emits a JSON array."""
    result = runner.invoke(
        app,
        ["lane", "lease", "show", str(tmp_path), "default", "somelane", "--json"],
    )
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed == []  # no leases on a fresh lane
