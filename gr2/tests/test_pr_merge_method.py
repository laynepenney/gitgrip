"""Merge-method contract for gr2, ported from gr1's seven-round hardening (grip#842).

Written TDD-first: these must fail until `python_cli/pr.py` implements the contract.

The defect being designed out: gr1's `gr pr merge` **actively chose squash**. It asked the
host which methods were permitted and took the first of `squash > merge > rebase`,
delegating a workspace-policy decision to a party with no knowledge of the workspace.

gr2 today has the same class in a form that is harder to see, because there is no wrong
line to point at -- there is only an absent one. `python_cli/platform.py` invokes
`gh pr merge <n> --repo <r>` with **no strategy flag at all**, so the method is decided by
gh and the host, wholesale.

Guarantee 1 (grip#842): the host is asked *whether*, never *which*. Precedence is
explicit `--method`, then workspace setting, then a merge commit. An unpermitted method is
**refused, not substituted** -- silent substitution is the original defect in a politer
form, where the operator asks for one strategy, another happens, and the only way to find
out is counting parents afterwards.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from python_cli.pr import (  # noqa: E402
    MergeMethod,
    UnpermittedMergeMethodError,
    resolve_merge_method,
)


class TestPrecedence:
    """Explicit beats configured beats a merge commit. Nothing else participates."""

    def test_explicit_wins_over_configured(self):
        assert resolve_merge_method(explicit="rebase", configured="squash") is MergeMethod.REBASE

    def test_configured_used_when_no_explicit(self):
        assert resolve_merge_method(explicit=None, configured="squash") is MergeMethod.SQUASH

    def test_default_is_a_merge_commit(self):
        """The only method that preserves both parents is the one you get by saying nothing.

        This is the assertion that would have caught gr1's defect directly: there, saying
        nothing produced a squash.
        """
        assert resolve_merge_method(explicit=None, configured=None) is MergeMethod.MERGE

    @pytest.mark.parametrize("bad", ["", "  ", "Squash", "fast-forward", "merge-commit", "none"])
    def test_an_unrecognised_name_is_an_error_not_a_fallback(self, bad):
        """Falling back to the default on a name we do not recognise is silent substitution.

        The operator typed something. Guessing what they meant, or quietly ignoring it, is
        the same failure as letting the host choose -- a strategy happens that nobody asked
        for. Note `Squash` is in this list deliberately: near-misses are the realistic
        input, and case-insensitive acceptance is a decision, not a courtesy.
        """
        with pytest.raises(ValueError):
            resolve_merge_method(explicit=bad, configured=None)

    def test_an_unrecognised_CONFIGURED_name_is_also_an_error(self):
        """A bad value in the workspace file is not more trustworthy than a bad flag.

        It is less visible, which makes silent fallback worse here, not better: nobody is
        watching a config file at the moment of a merge.
        """
        with pytest.raises(ValueError):
            resolve_merge_method(explicit=None, configured="sqush")


class TestRefuseNeverSubstitute:
    """The paired control. Neither test means anything without the other.

    A guard that refuses everything passes the refusal test while breaking all merging;
    a guard that refuses nothing passes the permitted test while restoring the defect.
    Only the pair pins the behaviour, and each names what the other proves.
    """

    def test_a_permitted_method_is_used_verbatim(self):
        """POSITIVE CONTROL. Proves the guard is not simply refusing everything."""
        chosen = resolve_merge_method(
            explicit="squash", configured=None, permitted=["merge", "squash"]
        )
        assert chosen is MergeMethod.SQUASH

    def test_an_unpermitted_method_is_REFUSED(self):
        """NEGATIVE CONTROL. Proves the guard is not simply permitting everything."""
        with pytest.raises(UnpermittedMergeMethodError):
            resolve_merge_method(explicit="squash", configured=None, permitted=["merge"])

    def test_refusal_does_not_fall_back_to_a_permitted_method(self):
        """The whole guarantee, stated as the thing that must NOT happen.

        gr1's defect was not that it chose badly. It was that it chose AT ALL, then
        reported success, so the operator's request and the actual outcome differed with
        nothing in the output saying so. Raising is the only outcome that cannot be
        mistaken for the request having been honoured.
        """
        with pytest.raises(UnpermittedMergeMethodError) as excinfo:
            resolve_merge_method(explicit="rebase", configured=None, permitted=["merge", "squash"])

        # The error must name what was ASKED FOR, not merely what is allowed -- an operator
        # reading it needs to see their own request refused, not a list of alternatives
        # that reads like a suggestion to pick one.
        assert "rebase" in str(excinfo.value)

    def test_permitted_None_means_unchecked_not_unrestricted(self):
        """`permitted=None` is 'we did not ask the host', which must not read as 'anything goes'.

        This is guarantee 4 in miniature: unverifiable must be distinguishable from
        verified. Here the distinction is that no refusal is claimed either way -- the
        method resolves, and nothing asserts it was permitted.
        """
        assert resolve_merge_method(explicit="rebase", configured=None, permitted=None) is (
            MergeMethod.REBASE
        )


class TestTheFlagActuallyReachesGh:
    """Resolving a method proves nothing if the resolved value is never passed on.

    gr1's lesson, stated as guarantee 3: pinning a function does not pin its invocation.
    A correct `resolve_merge_method` with a caller that still shells out to a bare
    `gh pr merge` is exactly the defect we started with, and every test above would pass.
    """

    def test_the_resolved_method_appears_in_the_gh_argv(self, monkeypatch):
        """Asserts the argv gh actually receives -- behaviour, not internal structure.

        Monkeypatching `subprocess.run` rather than subclassing keeps the test from
        prescribing how the adapter is built, so a later refactor cannot make it
        vacuously green by moving the call somewhere the subclass no longer intercepts.
        """
        from python_cli import platform as platform_mod

        recorded: list[list[str]] = []

        class _Proc:
            returncode = 0
            stdout = "{}"
            stderr = ""

        def _fake_run(argv, *a, **kw):
            recorded.append(list(argv))
            return _Proc()

        monkeypatch.setattr(platform_mod.subprocess, "run", _fake_run)
        platform_mod.GitHubAdapter().merge_pr("owner/repo", 42, method=MergeMethod.SQUASH)

        assert recorded, "the adapter never invoked gh at all"
        argv = recorded[0]
        assert "--squash" in argv, (
            f"the resolved method never reached gh; argv was {argv}. A method decided and "
            f"then dropped is indistinguishable from one never decided."
        )

    def test_no_method_still_names_one_explicitly(self, monkeypatch):
        """The absent flag IS the defect, so the default must be a POSITIVE assertion.

        A test that only checks `--squash` when squash is asked for would stay green
        against today's code path for every other case -- and today's code path passes no
        flag at all, which is how the host ends up choosing.
        """
        from python_cli import platform as platform_mod

        recorded: list[list[str]] = []

        class _Proc:
            returncode = 0
            stdout = "{}"
            stderr = ""

        monkeypatch.setattr(
            platform_mod.subprocess,
            "run",
            lambda argv, *a, **kw: (recorded.append(list(argv)), _Proc())[1],
        )
        platform_mod.GitHubAdapter().merge_pr(
            "owner/repo", 42, method=resolve_merge_method(explicit=None, configured=None)
        )

        argv = recorded[0]
        assert "--merge" in argv, (
            f"no strategy flag reached gh; argv was {argv}. With no flag, gh and the host "
            f"decide -- which is guarantee 1's failure in its least visible form, because "
            f"there is no wrong line to point at, only an absent one."
        )


class TestTheConfiguredWorkspaceMethodIsActuallyREACHED:
    """The resolver being correct proves nothing if production never calls it.

    Sentinel's r1 mutation: replace production method resolution with the constant
    `MergeMethod.MERGE` and all 56 tests stay green -- because every caller passed
    `configured=None`, so the workspace setting was never read and the default was the
    only value the resolver could return. The resolver was correct and UNREACHED, which
    is guarantee 3 again: pinning a function does not pin its invocation.

    These tests fail if the constant is substituted, because they require a NON-default
    method to arrive at the adapter by way of the workspace file.
    """

    def _workspace(self, tmp_path, method: str | None):
        import json as _json

        spec = '\nschema_version = 1\nworkspace_name = "w"\n\n[[repos]]\nname = "app"\npath = "repos/app"\nurl = "https://example.invalid/app.git"\n'
        if method is not None:
            spec += f'\n[workspace_constraints]\nmerge_method = "{method}"\n'
        (tmp_path / ".grip").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".grip" / "workspace_spec.toml").write_text(spec)
        return tmp_path

    def test_the_workspace_setting_is_read_from_the_spec(self, tmp_path):
        from python_cli.app import _configured_merge_method

        assert _configured_merge_method(self._workspace(tmp_path, "squash")) == "squash"

    def test_absent_setting_reads_as_None_not_as_a_default(self, tmp_path):
        """`None` means the workspace said nothing, which the resolver turns into a merge
        commit. Returning the string "merge" here would collapse 'unset' and 'chose
        merge' into one value, and a later change of default would silently never reach
        the workspaces that never expressed a preference."""
        from python_cli.app import _configured_merge_method

        assert _configured_merge_method(self._workspace(tmp_path, None)) is None

    def test_a_configured_method_reaches_resolution(self, tmp_path):
        """End of the wire: spec file -> helper -> resolver -> a NON-default method.

        This is the assertion the constant-MERGE mutation cannot satisfy.
        """
        from python_cli.app import _configured_merge_method

        configured = _configured_merge_method(self._workspace(tmp_path, "squash"))
        assert resolve_merge_method(explicit=None, configured=configured) is MergeMethod.SQUASH

    def test_explicit_still_beats_the_workspace_setting(self, tmp_path):
        from python_cli.app import _configured_merge_method

        configured = _configured_merge_method(self._workspace(tmp_path, "squash"))
        assert resolve_merge_method(explicit="rebase", configured=configured) is MergeMethod.REBASE


class TestTheCLICallSiteActuallyResolves:
    """Pins the INVOCATION, not the resolver -- because the resolver was already correct.

    The first version of the P1-TWO fix added tests for `_configured_merge_method` and
    for `resolve_merge_method`, both passing, and Sentinel's mutation SURVIVED: replacing
    the CLI's resolution with the constant `MergeMethod.MERGE` left all of them green,
    because none of them traversed the call site. Guarantee 3, inside the fix for a
    guarantee-3 finding, on the third occurrence of the same shape in one change.

    The only assertion that can distinguish "resolved" from "constant" is one that
    observes what the CLI HANDS DOWNSTREAM when the workspace asks for a NON-default
    method.
    """

    def test_a_squash_workspace_makes_the_CLI_pass_SQUASH_downstream(
        self, tmp_path, monkeypatch
    ):
        import json as _json

        from typer.testing import CliRunner

        from python_cli import app as app_mod

        (tmp_path / ".grip").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".grip" / "workspace_spec.toml").write_text(
            '\nschema_version = 1\nworkspace_name = "w"\n\n'
            '[workspace_constraints]\nmerge_method = "squash"\n'
        )
        group = {"pr_group_id": "pg", "owner_unit": "apollo", "lane_name": "lane", "prs": []}
        gpath = tmp_path / "g.json"
        gpath.write_text(_json.dumps(group))

        seen: dict[str, object] = {}

        monkeypatch.setattr(app_mod, "_resolve_lane_name", lambda *a, **k: "lane")
        monkeypatch.setattr(app_mod, "_find_pr_group", lambda *a, **k: (gpath, group))
        monkeypatch.setattr(app_mod, "get_platform_adapter", lambda *a, **k: object())
        monkeypatch.setattr(
            app_mod.pr_ops,
            "merge_pr_group",
            lambda **kw: seen.update(kw) or {"completed": []},
        )

        CliRunner().invoke(app_mod.app, ["pr", "merge", str(tmp_path), "apollo", "lane", "--json"])

        assert seen.get("method") is MergeMethod.SQUASH, (
            f"the CLI handed down {seen.get('method')!r}. The workspace configured "
            f"'squash'; a constant, or an unwired `configured=None`, yields MERGE and is "
            f"indistinguishable from a correct default."
        )

    def test_an_explicit_flag_still_overrides_the_workspace_at_the_CLI(
        self, tmp_path, monkeypatch
    ):
        import json as _json

        from typer.testing import CliRunner

        from python_cli import app as app_mod

        (tmp_path / ".grip").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".grip" / "workspace_spec.toml").write_text(
            '\nschema_version = 1\nworkspace_name = "w"\n\n'
            '[workspace_constraints]\nmerge_method = "squash"\n'
        )
        group = {"pr_group_id": "pg", "owner_unit": "apollo", "lane_name": "lane", "prs": []}
        gpath = tmp_path / "g.json"
        gpath.write_text(_json.dumps(group))
        seen: dict[str, object] = {}

        monkeypatch.setattr(app_mod, "_resolve_lane_name", lambda *a, **k: "lane")
        monkeypatch.setattr(app_mod, "_find_pr_group", lambda *a, **k: (gpath, group))
        monkeypatch.setattr(app_mod, "get_platform_adapter", lambda *a, **k: object())
        monkeypatch.setattr(
            app_mod.pr_ops,
            "merge_pr_group",
            lambda **kw: seen.update(kw) or {"completed": []},
        )

        CliRunner().invoke(
            app_mod.app,
            ["pr", "merge", str(tmp_path), "apollo", "lane", "--json", "--method", "rebase"],
        )
        assert seen.get("method") is MergeMethod.REBASE
