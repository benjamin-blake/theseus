"""Contract tests for bin/setup-cloud-env.sh without executing networked installers."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

import botocore.session
import pytest

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


def test_github_mcp_token_comment_writes_the_proxy_placeholder() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    assert "#     printf 'proxy-injected\\n' > \"$HOME/.config/gh-mcp/token\"\n" in script
    assert "<PAT>" not in script
    assert "GITHUB_MCP_PAT" not in script


_PLACEHOLDER_NAME = "aws-proxy-placeholder-credentials"


def _header_block(script: str, start_marker: str, end_marker: str) -> list[str]:
    lines = script.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(start_marker))
    end = next(i for i in range(start, len(lines)) if lines[i].startswith(end_marker))
    return [line[2:] if line.startswith("# ") else "" for line in lines[start + 1 : end] if line.startswith("#")]


def _template_block(script: str, admin: bool) -> str:
    dev = _header_block(script, "# DEV environment", "# boto3 then resolves")
    body = [line.removeprefix("    ") for line in dev if line.startswith("    ")]
    body = [line for line in body if not line.startswith("cd /home/user/ontheloop")]
    if admin:
        admin_lines = _header_block(script, "# ADMIN environment", "# and set this")
        start = next(i for i, line in enumerate(admin_lines) if line.startswith("    [profile"))
        profile = [line.removeprefix("    ") for line in admin_lines[start:] if line.startswith("    ")]
        eof = max(i for i, line in enumerate(body) if line == "EOF")
        body = body[:eof] + [""] + profile + body[eof:]
    text = "\n".join(body) + "\n"
    return text.replace("<ACCOUNT_ID>", "acct").replace("<PLACEHOLDER>", "extid")


def _install_block(script: str) -> str:
    start = script.index("# 2b. credential_process placeholder")
    end = script.index("# 3. AWS CLI v2")
    return script[start:end]


def _run_template(tmp_path: Path, admin: bool) -> tuple[Path, subprocess.CompletedProcess[str]]:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    home = tmp_path / "home"
    (home / ".aws").mkdir(parents=True)
    (home / ".aws" / "credentials").write_text("[agent_static]\naws_access_key_id = stale\n", encoding="utf-8")
    harness = f"REPO_ROOT={Path.cwd()}\nlog() {{ :; }}\n" + _template_block(script, admin) + _install_block(script)
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    result = subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, encoding="utf-8", env=env, timeout=30, check=False
    )
    return home, result


def _resolve(home: Path, profile: str, monkeypatch: pytest.MonkeyPatch) -> botocore.session.Session:
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(home / ".aws" / "config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(home / ".aws" / "credentials"))
    return botocore.session.Session(profile=profile)


def test_proxy_template_resolves_agent_static_through_credential_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for admin in (False, True):
        sub = tmp_path / ("admin" if admin else "dev")
        sub.mkdir()
        home, result = _run_template(sub, admin)
        assert result.returncode == 0, result.stderr
        assert not (home / ".aws" / "credentials").exists()
        config = (home / ".aws" / "config").read_text(encoding="utf-8")
        assert "[profile agent_platform]" in config
        assert ("[profile agent_platform_admin]" in config) is admin
        assert config.count("sts_regional_endpoints = regional") == (2 if admin else 1)
        creds = _resolve(home, "agent_static", monkeypatch).get_credentials()
        assert creds.access_key == "proxy-injected-key-id"


def test_placeholder_install_precedes_first_aws_call() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    install = script.index("install -m 0755")
    assert install < script.index("aws s3 sync")
    assert install < script.index("bash .claude/hooks/session_start_aws.sh")
    assert install < script.index('bash "$REPO_ROOT/bin/sync-deps.sh"')


def test_placeholder_install_is_idempotent(tmp_path: Path) -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    harness = f"REPO_ROOT={Path.cwd()}\nlog() {{ :; }}\nset -euo pipefail\n{_install_block(script)}\n{_install_block(script)}"
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, env=env, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    installed = home / ".local" / "bin" / _PLACEHOLDER_NAME
    assert installed.read_bytes() == (Path("bin") / _PLACEHOLDER_NAME).read_bytes()
    assert os.access(installed, os.X_OK)


def test_header_template_has_no_static_key_and_current_path() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    assert "aws_secret_access_key" not in script
    assert "/home/user/agent-platform" not in script
    assert "cd /home/user/ontheloop && bash bin/setup-cloud-env.sh" in script
    allowed = re.search(r"allowed host (\S+) ONLY", script)
    assert allowed is not None
    assert allowed.group(1) == "sts.eu-west-2.amazonaws.com"
    assert "network secret" in script


def test_admin_template_sets_install_terraform_inline() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    admin = "\n".join(_header_block(script, "# ADMIN environment", "# Identity checks"))
    assert "cd /home/user/ontheloop && INSTALL_TERRAFORM=1 bash bin/setup-cloud-env.sh" in admin
    assert "BEFORE or AFTER" in admin
    dev = "\n".join(_header_block(script, "# DEV environment", "# boto3 then resolves"))
    assert "INSTALL_TERRAFORM" not in dev


def _role_max_session(resource: str) -> int:
    tf = Path("terraform/bootstrap/platform_roles.tf").read_text(encoding="utf-8")
    match = re.search(r'resource "aws_iam_role" "' + resource + r'" \{.*?max_session_duration\s*=\s*(\d+)', tf, re.DOTALL)
    assert match is not None
    return int(match.group(1))


def test_template_duration_seconds_fit_each_roles_max_session_duration() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    dev = "\n".join(_header_block(script, "# DEV environment", "# boto3 then resolves"))
    admin = "\n".join(_header_block(script, "# ADMIN environment", "# and set this"))
    dev_seconds = int(re.search(r"duration_seconds = (\d+)", dev).group(1))
    admin_seconds = int(re.search(r"duration_seconds = (\d+)", admin).group(1))
    assert dev_seconds <= _role_max_session("platform_dev")
    assert admin_seconds <= _role_max_session("platform_admin")


def _run_admin_block_recording_profile(tmp_path: Path, preset_profile: str | None) -> str:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    block = _extract_install_terraform_block(script)
    root = tmp_path / "repo"
    delegate_dir = root / ".github" / "actions" / "materialise-tfvars"
    delegate_dir.mkdir(parents=True)
    record = tmp_path / "profile.txt"
    delegate = delegate_dir / "materialise_tfvars.sh"
    delegate.write_text(f'#!/usr/bin/env bash\nprintf "%s" "${{AWS_PROFILE-unset}}" > "{record}"\n', encoding="utf-8")
    delegate.chmod(delegate.stat().st_mode | stat.S_IEXEC)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aws = fake_bin / "aws"
    fake_aws.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IEXEC)
    home = tmp_path / "home"
    home.mkdir()
    harness = f"log() {{ :; }}\nREPO_ROOT={root}\nHOME={home}\nINSTALL_TERRAFORM=1\n{block}\n"
    env = {"PATH": f"{fake_bin}:{os.environ['PATH']}"}
    if preset_profile is not None:
        env["AWS_PROFILE"] = preset_profile
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", harness], capture_output=True, text=True, env=env, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    return record.read_text(encoding="utf-8")


def test_admin_block_defaults_aws_profile_when_unset(tmp_path: Path) -> None:
    assert _run_admin_block_recording_profile(tmp_path, None) == "agent_platform_admin"


def test_admin_block_keeps_an_explicit_aws_profile(tmp_path: Path) -> None:
    assert _run_admin_block_recording_profile(tmp_path, "agent_platform") == "agent_platform"
