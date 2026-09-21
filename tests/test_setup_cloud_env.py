"""Contract tests for bin/setup-cloud-env.sh without executing networked installers."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

SETUP_SCRIPT = Path("bin/setup-cloud-env.sh")

_INSTALL_TERRAFORM_IF = 'if [ "${INSTALL_TERRAFORM:-0}" = "1" ]; then'
_DELEGATE_CALL = 'bash "$REPO_ROOT/.github/actions/materialise-tfvars/materialise_tfvars.sh"'


def _extract_install_terraform_block(script: str) -> str:
    """Return the INSTALL_TERRAFORM=1 branch's full if/else/fi block, delimited by the unique
    `if [ "${INSTALL_TERRAFORM:-0}" = "1" ]; then` literal and its MATCHING `else`/`fi` -- found
    by tracking if/then-fi nesting depth, not a hardcoded line number, so a future edit inside the
    block (like this plan's own insertion) cannot silently make the extraction hit the WRONG
    (nested, mirror-sync) `else` at depth 2 instead of the outer one at depth 1.
    """
    lines = script.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == _INSTALL_TERRAFORM_IF)
    depth = 1
    end = None
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.endswith("; then") or stripped == "then":
            depth += 1
        elif stripped == "fi":
            depth -= 1
            if depth == 0:
                end = i
                break
    assert end is not None, "no matching outer fi found for the INSTALL_TERRAFORM=1 branch"
    return "\n".join(lines[start : end + 1])


class TestAdminTfvarsFetch:
    def test_admin_branch_calls_shared_delegate(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")
        block = _extract_install_terraform_block(script)
        assert block.count(_DELEGATE_CALL) == 1
        # Warn-and-continue, not bare -- the call must sit inside its OWN if/else, never a bare
        # statement that would abort the script under inherited errexit on a failed fetch.
        delegate_line_idx = next(i for i, line in enumerate(block.splitlines()) if _DELEGATE_CALL in line)
        block_lines = block.splitlines()
        assert "if" in block_lines[delegate_line_idx]
        else_idx = next(i for i in range(delegate_line_idx, len(block_lines)) if block_lines[i].strip() == "else")
        assert else_idx > delegate_line_idx
        assert "WARNING" in block_lines[else_idx + 1]

    def test_failed_fetch_does_not_abort(self) -> None:
        # Executes the REAL extracted block (not a grep) under the literal errexit invocation
        # bin/setup-cloud-env.sh itself runs under (`set -euo pipefail`), with a stub delegate
        # that exits 1 to simulate a failed fetch -- proving the warn-and-continue construct
        # actually suppresses errexit rather than aborting before the session_start hooks.
        script = SETUP_SCRIPT.read_text(encoding="utf-8")
        block = _extract_install_terraform_block(script)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_repo_root = tmp_path / "repo"
            delegate_dir = fake_repo_root / ".github" / "actions" / "materialise-tfvars"
            delegate_dir.mkdir(parents=True)
            stub_delegate = delegate_dir / "materialise_tfvars.sh"
            stub_delegate.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            stub_delegate.chmod(stub_delegate.stat().st_mode | stat.S_IEXEC)

            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            fake_aws = fake_bin / "aws"
            # Simulate a failed/absent mirror sync (non-fatal) so the block reaches the delegate
            # call without a real network dependency -- the mirror-sync branch is not under test.
            fake_aws.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IEXEC)

            fake_home = tmp_path / "home"
            fake_home.mkdir()

            marker = "POST_FETCH_LINE_REACHED"
            harness = (
                'log() { printf "[setup] %s\\n" "$*"; }\n'
                f"REPO_ROOT={fake_repo_root}\n"
                f"HOME={fake_home}\n"
                "INSTALL_TERRAFORM=1\n"
                f"{block}\n"
                f"echo {marker}\n"
            )

            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

            result = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", harness],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )

        assert result.returncode == 0, result.stderr
        assert marker in result.stdout
        assert "WARNING: materialise-tfvars fetch failed" in result.stdout


def test_shared_session_bootstrap_steps_are_ordered_after_prerequisites() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    ordered_commands = (
        'bash "$REPO_ROOT/bin/sync-deps.sh"',
        'bash "$REPO_ROOT/bin/ensure-github-mcp-server.sh"',
        "bash .claude/hooks/session_start_aws.sh",
        "bash .claude/hooks/session_start_precommit.sh",
        "bash .claude/hooks/session_start_sync_main.sh",
    )

    positions = [script.index(command) for command in ordered_commands]
    assert positions == sorted(positions)
    assert script.index("set -euo pipefail") < positions[0]
    assert script.index('REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"') < positions[0]


def test_setup_contract_uses_delegated_bootstrap_commands() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    assert script.count('bash "$REPO_ROOT/bin/sync-deps.sh"') == 1
    assert script.count('bash "$REPO_ROOT/bin/ensure-github-mcp-server.sh"') == 1
    assert script.count("bash .claude/hooks/session_start_aws.sh") == 1
    assert script.count("bash .claude/hooks/session_start_precommit.sh") == 1
    assert script.count("bash .claude/hooks/session_start_sync_main.sh") == 1


def test_github_readiness_runs_after_mcp_install_and_before_precommit() -> None:
    script = Path("bin/setup-cloud-env.sh").read_text(encoding="utf-8")
    readiness = script.index("bash .claude/hooks/session_start_github_readiness.sh")
    assert readiness > script.index("ensure-github-mcp-server.sh")
    assert readiness < script.index("bash .claude/hooks/session_start_precommit.sh")
