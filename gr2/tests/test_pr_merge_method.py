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
