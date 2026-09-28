"""Hermetic terraform lock/required_providers coherence guard (rec-4110/3400/3318/3369/3919).

Enforces a policy stricter than terraform itself: every provider pinned in a committed
`.terraform.lock.hcl` must be explicitly declared in that root's `required_providers` block, and
every declared provider must have a matching lock entry. Two drift classes only:

- orphan: a lock entry with no matching required_providers declaration (today's pre-fix defect --
  the vestigial hashicorp/null block left behind by #969's null_resource removal).
- missing: a required_providers declaration with no matching lock entry.

Deliberately NOT gated: a provider `version` constraint changing while the locked version still
satisfies it (e.g. `~> 5.0` -> `>= 5.0`). Measured at planning time (Terraform 1.10.5): neither
plain `init` nor `-lockfile=readonly` init compares or rewrites the lock's `constraints` string in
that case -- only `terraform providers lock` / `init -upgrade` do -- so constraints-string drift
never dirties the tree and never escapes detection; gating on it would add a finding whose
remediation needs provider egress while guarding no tree-dirtying hazard.

The native `-lockfile=readonly` check wired into scripts/checks/_terraform.py is authoritative
wherever terraform actually runs (it also catches hash-only drift, which this parser cannot see).
This hermetic parser exists because the --pre tier has no terraform binary and no provider egress
(Decision 119), so it is the only guard that runs on every terraform/lock-touching diff.

Residuals (not caught by this module, all caught natively by readonly init in terraform-validate):
hash-only drift, constraints-string drift, and an implicitly required provider (a resource type
used but never declared in required_providers and absent from the lock).

Limitation: a trailing `#`/`//` comment, or a `/* */` block comment containing a brace, inside a
required_providers block can mis-match braces. The effect fails closed -- a spurious finding, never
a false pass.
"""

from __future__ import annotations

import re

from scripts.checks import _common, registry
from scripts.checks._terraform import tracked_lock_files
from scripts.checks.iam_tf.validate_terraform_try import _blank_comment_lines

_LOCK_PROVIDER_RE = re.compile(r'^provider\s+"([^"]+)"\s*\{', re.MULTILINE)
_REQUIRED_PROVIDERS_RE = re.compile(r"\brequired_providers\s*\{")
_LOCAL_ENTRY_RE = re.compile(r"[ \t]*([A-Za-z_][A-Za-z0-9_-]*)[ \t]*=[ \t]*")
_SOURCE_RE = re.compile(r'\bsource\s*=\s*"([^"]+)"')
_STRING_LITERAL_RE = re.compile(r'"[^"]*"')


def _block_end(content: str, open_brace_pos: int) -> int:
    """Return the index just past the '}' that closes the '{' at open_brace_pos."""
    depth = 0
    i = open_brace_pos
    while i < len(content):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(content)


def _normalize_source(source: str) -> str | None:
    """Lower-case the source; a 2-part `ns/type` is prefixed `registry.terraform.io/`, a 3-part
    `host/ns/type` is kept as-is. `terraform.io/builtin/*` (the built-in `terraform` provider) is
    ignored -- it is never lock-pinned."""
    s = source.strip().lower()
    parts = s.split("/")
    if len(parts) == 3:
        if parts[0] == "terraform.io" and parts[1] == "builtin":
            return None
        return s
    if len(parts) == 2:
        return f"registry.terraform.io/{s}"
    return None


def _parse_required_providers_entries(block: str) -> set[str]:
    """Single left-to-right scan of a required_providers block's inner content: each top-level
    `name = { ... }` or `name = "..."` entry is consumed whole (including its nested object body,
    which is skipped over rather than re-scanned) so a `source`/`version` key inside an entry's
    own object is never mistaken for a second top-level entry."""
    addrs: set[str] = set()
    pos = 0
    while pos < len(block):
        m = _LOCAL_ENTRY_RE.match(block, pos)
        if not m:
            pos += 1
            continue
        local_name = m.group(1).strip().lower()
        after = m.end()
        if after < len(block) and block[after] == "{":
            obj_end = _block_end(block, after)
            obj_content = block[after + 1 : obj_end - 1]
            source_m = _SOURCE_RE.search(obj_content)
            addr = _normalize_source(source_m.group(1)) if source_m else f"registry.terraform.io/hashicorp/{local_name}"
            pos = obj_end
        elif after < len(block) and block[after] == '"':
            # Legacy string-shorthand entry (`name = "<version constraint>"`): the string is a
            # version constraint, not a source -- the source is implicitly hashicorp.
            str_m = _STRING_LITERAL_RE.match(block, after)
            addr = f"registry.terraform.io/hashicorp/{local_name}"
            pos = str_m.end() if str_m else after
        else:
            pos = after
            continue
        if addr is not None:
            addrs.add(addr)
    return addrs


def _declared_addresses(tf_texts: list[str]) -> set[str]:
    """Every provider address declared across every required_providers block in tf_texts."""
    declared: set[str] = set()
    for raw in tf_texts:
        content = _blank_comment_lines(raw)
        for m in _REQUIRED_PROVIDERS_RE.finditer(content):
            brace_pos = content.index("{", m.start())
            end = _block_end(content, brace_pos)
            block = content[brace_pos + 1 : end - 1]
            declared |= _parse_required_providers_entries(block)
    return declared


def lock_coherence_findings(lock_text: str, tf_texts: list[str]) -> list[str]:
    """Pure: one finding per orphaned lock entry or undeclared-but-locked provider. Empty list
    means every lock entry has a matching required_providers declaration and vice versa."""
    lock_addrs = {m.group(1).strip().lower() for m in _LOCK_PROVIDER_RE.finditer(lock_text)}
    declared_addrs = _declared_addresses(tf_texts)

    findings: list[str] = []
    for addr in sorted(lock_addrs - declared_addrs):
        findings.append(
            f"orphan: lock entry {addr!r} has no matching declaration in any required_providers "
            "block -- regenerate the lock (`terraform init -backend=false`, no -upgrade) and "
            "commit it, or declare the provider explicitly"
        )
    for addr in sorted(declared_addrs - lock_addrs):
        findings.append(
            f"missing: required_providers declares {addr!r} but the lock has no matching entry -- "
            "regenerate the lock (`terraform init -backend=false`); a new third-party provider's "
            "entry comes from `terraform providers lock` on an egress-capable container"
        )
    return findings


@registry.register("validate_terraform_lock_coherence", owner="platform")
def validate_terraform_lock_coherence(failed: list[str]) -> None:
    """Every git-tracked terraform lock file is coherent with its root's required_providers."""
    print("\n=== Terraform lock coherence ===")
    tracked = tracked_lock_files(_common.ROOT)
    if tracked is None:
        reason = "git unavailable -- could not determine tracked lock files"
        print(f"  SKIP: {reason}")
        registry.skipped(reason)
        return

    any_failed = False
    for lock_rel in tracked:
        lock_path = _common.ROOT / lock_rel
        root_dir = lock_path.parent
        lock_text = lock_path.read_text(encoding="utf-8")
        tf_texts = [p.read_text(encoding="utf-8") for p in sorted(root_dir.glob("*.tf"))]
        findings = lock_coherence_findings(lock_text, tf_texts)
        if findings:
            any_failed = True
            print(f"  {lock_rel}:")
            for finding in findings:
                print(f"    - {finding}")

    if any_failed:
        failed.append("Terraform lock coherence")
    else:
        print(f"All {len(tracked)} tracked terraform lock file(s) are coherent with their root's required_providers.")

    registry.examined(len(tracked), unit="lock_files")


if __name__ == "__main__":  # pragma: no cover
    _failed: list[str] = []
    validate_terraform_lock_coherence(_failed)
    for _f in _failed:
        print(f"  - {_f}")
    raise SystemExit(1 if _failed else 0)
