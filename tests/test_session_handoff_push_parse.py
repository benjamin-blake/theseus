"""Mirror tests for scripts/session/handoff_push_parse.py (100% coverage floor)."""

from __future__ import annotations

import pytest

from scripts.session.handoff_push_parse import NonCanonical, ParsedPush, is_push_shaped, parse_canonical

PUSH_SHAPED_CASES = [
    ("timeout wrapper", "timeout 120 git push"),
    ("env-prefixed wrapper", "env GIT_TRACE=1 git push"),
    ("command wrapper", "command git push"),
    ("nohup wrapper", "nohup git push"),
    ("time wrapper", "time git push"),
    ("bang wrapper", "! git push"),
    ("subshell grouping", "(git push)"),
    ("brace grouping", "{ git push; }"),
    ("if-then-fi control flow", "if true; then git push; fi"),
    ("dollar-paren substitution", "echo $(git push origin main)"),
    ("backtick substitution", "echo `git push origin main`"),
    ("commit -m with real push substitution", 'git commit -m "$(git push origin main)"'),
    ("combined-flag shell -lc", 'bash -lc "git push origin main"'),
    ("shell-fed heredoc", "cat <<EOF | bash\ngit push origin main\nEOF\n"),
    ("multi-line command", "git status\ngit push origin main"),
    ("comment-newline form", "git status # check\ngit push origin main"),
    ("push after quoted heredoc marker", 'grep -n "<<EOF" f\ngit push origin main'),
    ("timeout bash -c", "timeout 60 bash -c 'git push origin main'"),
    ("env sh -c", "env sh -c 'git push origin main'"),
    ("eval quoted", "eval 'git push origin main'"),
    ("cat piped-to-shell heredoc with push body", "cat <<'EOF' | bash\ngit push origin main\nEOF\n"),
    ("backslash-newline split push", "git \\\npush -u origin HEAD"),
    (
        "quoted heredoc whose last body line ends in backslash, push after delimiter",
        "cat <<'EOF'\nsome data \\\nEOF\ngit push origin main",
    ),
    ("bash -c fed by printf substitution containing push", "bash -c \"$(printf 'git push origin main')\""),
    ("send-pack", "git send-pack origin main"),
    ("http-push", "git http-push origin main"),
    ("subtree push", "git subtree push --prefix=x origin main"),
    ("lfs push", "git lfs push origin main"),
    ("config-env alias", "git -c alias.p=push p"),
    ("unknown global option before subcommand", "git --unknown-global push origin main"),
    ("accepted false positive echo", "echo git push"),
]

NOT_PUSH_SHAPED_CASES = [
    ("git log --grep push", "git log --grep push"),
    ("git --no-pager log --grep push", "git --no-pager log --grep push"),
    ("commit message literally push fix", 'git commit -m "push fix"'),
    (
        "commit -m fed by heredoc-substitution containing a real push (data, not shell-fed)",
        "git commit -m \"$(cat <<'EOF'\nnotes about git push\nEOF\n)\"",
    ),
    ("printf substitution mentioning git push as one fused token", "git commit -m \"$(printf 'explain git push')\""),
    ("comment mentions push, no real push", "git status # push later"),
    ("grep for the literal string", 'grep "git push" f'),
    ("heredoc body line mentioning push is data", "cat > f <<'EOF'\ngit push body line\nEOF\n"),
    ("assignment prefix before git non-push subcommand", "GIT_TRACE=1 git log --grep push"),
]


class TestPushShaped:
    @pytest.mark.parametrize("name,command", PUSH_SHAPED_CASES, ids=[c[0] for c in PUSH_SHAPED_CASES])
    def test_push_shaped_classifier_catches_wrapper_and_newline_forms(self, name: str, command: str) -> None:
        assert is_push_shaped(command) is True, f"{name!r} should be push-shaped: {command!r}"

    @pytest.mark.parametrize("name,command", NOT_PUSH_SHAPED_CASES, ids=[c[0] for c in NOT_PUSH_SHAPED_CASES])
    def test_not_push_shaped(self, name: str, command: str) -> None:
        assert is_push_shaped(command) is False, f"{name!r} should NOT be push-shaped: {command!r}"

    def test_tokenise_failure_fails_closed(self) -> None:
        assert is_push_shaped("git push 'unterminated") is True


CANONICAL_LITERALS = [
    "git push -u origin HEAD",
    "git push --set-upstream origin HEAD",
    "git push --force-with-lease -u origin main",
    "git push -u --force-with-lease origin main",
]


class TestCanonical:
    @pytest.mark.parametrize("command", CANONICAL_LITERALS)
    def test_instruction_surface_literals_are_canonical(self, command: str) -> None:
        assert isinstance(parse_canonical(command), ParsedPush)

    def test_bare_push_is_canonical(self) -> None:
        result = parse_canonical("git push")
        assert result == ParsedPush(kind="bare_push", worktree_hint=None, remote=None, src=None, dst=None)

    def test_delete_form_with_flag(self) -> None:
        result = parse_canonical("git push origin --delete somebranch")
        assert result == ParsedPush(kind="delete", worktree_hint=None, remote="origin", src=None, dst="somebranch")

    def test_delete_form_with_colon(self) -> None:
        result = parse_canonical("git push origin :somebranch")
        assert result == ParsedPush(kind="delete", worktree_hint=None, remote="origin", src=None, dst="somebranch")

    def test_dry_run_flag(self) -> None:
        result = parse_canonical("git push --dry-run origin main")
        assert isinstance(result, ParsedPush) and result.kind == "dry_run"

    def test_dry_run_short_flag(self) -> None:
        result = parse_canonical("git push -n origin main")
        assert isinstance(result, ParsedPush) and result.kind == "dry_run"

    def test_cd_prefix_resolves_worktree(self) -> None:
        result = parse_canonical("cd /tmp/wt && git push -u origin HEAD")
        assert isinstance(result, ParsedPush) and result.worktree_hint == "/tmp/wt"

    def test_dash_c_resolves_worktree(self) -> None:
        result = parse_canonical("git -C /tmp/wt push -u origin HEAD")
        assert isinstance(result, ParsedPush) and result.worktree_hint == "/tmp/wt"

    def test_option_order_insensitive(self) -> None:
        a = parse_canonical("git push -u --force-with-lease origin main")
        b = parse_canonical("git push --force-with-lease -u origin main")
        assert isinstance(a, ParsedPush) and isinstance(b, ParsedPush)
        assert a.remote == b.remote and a.src == b.src

    def test_canonical_wrapped_with_backslash_newline_stays_canonical(self) -> None:
        result = parse_canonical("git push \\\n-u origin HEAD")
        assert isinstance(result, ParsedPush)
        assert result.kind == "push"

    def test_two_refspecs_non_canonical(self) -> None:
        result = parse_canonical("git push origin main extra")
        assert isinstance(result, NonCanonical)

    def test_env_prefix_non_canonical(self) -> None:
        assert isinstance(parse_canonical("NAME=x git push origin main"), NonCanonical)

    def test_dash_c_option_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git -c foo.bar=baz push origin main"), NonCanonical)

    def test_force_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push --force origin main"), NonCanonical)

    def test_force_short_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push -f origin main"), NonCanonical)

    def test_no_verify_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push --no-verify origin main"), NonCanonical)

    def test_all_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push --all origin"), NonCanonical)

    def test_mirror_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push --mirror origin"), NonCanonical)

    def test_tags_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push --tags origin"), NonCanonical)

    def test_pipe_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin main | cat"), NonCanonical)

    def test_redirection_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin main > out.txt"), NonCanonical)

    def test_second_segment_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin main; echo done"), NonCanonical)

    def test_trailing_comment_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin main # comment"), NonCanonical)

    def test_force_prefix_refspec_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin +main:main"), NonCanonical)

    def test_not_a_git_command_non_canonical(self) -> None:
        assert isinstance(parse_canonical("echo push"), NonCanonical)

    def test_not_a_push_subcommand_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git commit -m push"), NonCanonical)

    def test_multiple_lines_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin main\ngit push origin main2"), NonCanonical)

    def test_unrecognised_option_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push --receive-pack=x origin main"), NonCanonical)

    def test_delete_without_branch_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin --delete"), NonCanonical)

    def test_malformed_refspec_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin :"), NonCanonical)

    def test_malformed_refspec_empty_dst_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push origin main:"), NonCanonical)

    def test_empty_command_non_canonical(self) -> None:
        assert isinstance(parse_canonical(""), NonCanonical)

    def test_dash_capital_c_without_path_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git -C"), NonCanonical)

    def test_tokenise_failure_non_canonical(self) -> None:
        assert isinstance(parse_canonical("git push 'unterminated"), NonCanonical)

    def test_bare_push_with_remote_no_refspec(self) -> None:
        result = parse_canonical("git push origin")
        assert result == ParsedPush(kind="bare_push", worktree_hint=None, remote="origin", src=None, dst=None)

    def test_explicit_src_and_dst_refspec(self) -> None:
        result = parse_canonical("git push origin main:refs/heads/main")
        assert result == ParsedPush(kind="push", worktree_hint=None, remote="origin", src="main", dst="refs/heads/main")


class TestInternalHelpers:
    """Direct coverage of private text-manipulation helpers not otherwise reachable through the
    public is_push_shaped / parse_canonical surface."""

    def test_find_delimiter_line_no_match(self) -> None:
        from scripts.session.handoff_push_parse import _find_delimiter_line

        text = "no delimiter here"
        assert _find_delimiter_line(text, 0, "EOF") == (len(text), len(text))

    def test_strip_heredocs_double_quote_escape(self) -> None:
        from scripts.session.handoff_push_parse import strip_heredocs

        text = 'echo "a\\"b" <<EOF\ndata\nEOF\ngit push origin main'
        assert "git push origin main" in strip_heredocs(text)

    def test_strip_heredocs_unterminated_at_end_of_text(self) -> None:
        from scripts.session.handoff_push_parse import strip_heredocs

        assert strip_heredocs("cat <<EOF") == "cat <<EOF"

    def test_find_balanced_spans_nested(self) -> None:
        from scripts.session.handoff_push_parse import _find_balanced_spans

        spans = _find_balanced_spans("echo $(git push $(echo origin) main)")
        assert len(spans) == 1
        assert "$(echo origin)" in spans[0][2]

    def test_extract_quoted_arg_double_quote_with_escape(self) -> None:
        from scripts.session.handoff_push_parse import _extract_quoted_arg

        assert _extract_quoted_arg('a\\"b"c', '"') == 'a\\"b'

    def test_extract_quoted_arg_double_quote_unterminated(self) -> None:
        from scripts.session.handoff_push_parse import _extract_quoted_arg

        assert _extract_quoted_arg("unterminated", '"') is None

    def test_shell_c_and_eval_args_double_quoted(self) -> None:
        from scripts.session.handoff_push_parse import _shell_c_and_eval_args

        args = _shell_c_and_eval_args('bash -c "a\\"b git push origin main"')
        assert args

    def test_eval_bareword_stops_at_newline(self) -> None:
        from scripts.session.handoff_push_parse import _shell_c_and_eval_args

        args = _shell_c_and_eval_args("eval git push origin main\nother thing")
        assert args and args[0] == "git push origin main"

    def test_eval_bareword_stops_at_semicolon(self) -> None:
        from scripts.session.handoff_push_parse import _shell_c_and_eval_args

        args = _shell_c_and_eval_args("eval git push origin main; other thing")
        assert args and args[0] == "git push origin main"

    def test_parse_git_subcommand_skips_leading_assignment(self) -> None:
        from scripts.session.handoff_push_parse import _parse_git_subcommand

        assert _parse_git_subcommand(["NAME=x", "git", "log"]) == ("log", False)

    def test_simple_command_push_shaped_empty_tokens(self) -> None:
        from scripts.session.handoff_push_parse import _simple_command_push_shaped

        assert _simple_command_push_shaped([]) is False
