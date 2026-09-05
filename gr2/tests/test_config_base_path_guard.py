"""Contract: ``config show`` / ``config apply`` refuse a non-file base path
instead of crashing.

Both verbs take ``base_path`` (a TOML file) and pass it to a library function
whose first line is ``base_path.read_text()``. Handed a directory -- which is
exactly what happens when someone invokes them like the other workspace verbs,
``gr2 config show <workspace_root>`` -- that raises
``IsADirectoryError: [Errno 21] Is a directory``, a traceback in front of the
user. A missing path raises ``FileNotFoundError`` the same way. A CLI should
refuse a bad argument, not traceback on it.

The witness travels the CLI, since the guard lives in the command wrappers.
"""

from __future__ import annotations

import json

import typer
from gr2.python_cli.grip_cli import config_cli_app
from tests.conftest import make_cli_runner

app = typer.Typer()
app.add_typer(config_cli_app, name="config")
runner = make_cli_runner()


# The discriminator is result.exception TYPE, not exit_code: CliRunner sets
# exit_code=1 for an uncaught exception too, and it does not print the
# traceback into result.output. A clean refusal raises typer.Exit -> SystemExit;
# the crash leaves IsADirectoryError / FileNotFoundError. Asserting exit_code
# alone passes on the crash (measured), so it is not a witness.
def _refused_cleanly(result) -> bool:
    return result.exit_code == 1 and isinstance(result.exception, SystemExit)


def test_config_show_refuses_a_directory(tmp_path):
    """Before the fix: ``IsADirectoryError`` in result.exception. After: a
    clean ``SystemExit`` at exit 1."""
    result = runner.invoke(app, ["config", "show", str(tmp_path)])
    assert _refused_cleanly(result), (result.exit_code, repr(result.exception))


def test_config_apply_refuses_a_directory(tmp_path):
    """The second verb with the same crash, guarded the same way."""
    result = runner.invoke(app, ["config", "apply", str(tmp_path)])
    assert _refused_cleanly(result), (result.exit_code, repr(result.exception))


def test_config_show_refuses_a_missing_path(tmp_path):
    """The other non-file shape: a path that does not exist at all
    (``FileNotFoundError`` before the fix)."""
    result = runner.invoke(app, ["config", "show", str(tmp_path / "nope.toml")])
    assert _refused_cleanly(result), (result.exit_code, repr(result.exception))


def test_config_show_still_reads_a_real_toml_file(tmp_path):
    """The control: a valid base TOML file must still be shown. Without this
    the guard could pass by refusing everything."""
    base = tmp_path / "config.toml"
    base.write_text('[spawn]\nsession_name = "synapt"\n')
    result = runner.invoke(app, ["config", "show", str(base), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["spawn"]["session_name"] == "synapt"
