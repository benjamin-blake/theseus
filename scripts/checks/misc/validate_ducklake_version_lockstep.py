from __future__ import annotations

import sys
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_ducklake_version_lockstep", owner="platform")
def validate_ducklake_version_lockstep(failed: list[str]) -> None:
    """Sub-second static gate: verify no derive surface diverges from config/lambda/ducklake/version.yaml.

    Checks:
    (a) requirements.in duckdb FLOOR == ">=<duckdb_version>" (sync_ducklake_version --check is clean),
        AND the compiled requirements.txt duckdb PIN satisfies that floor -- moving the floor without
        recompiling leaves the two halves of the cascade out of step.
    (b) No hardcoded duckdb version literal in src/common/ducklake_runtime.py or scripts/build_lambda.py
        (both must reach the pin only via the loader, not a literal).

    Eligible for both --pre fast-tier AND full presubmit (pure Python, sub-second).
    """
    print("\n=== DuckLake version lockstep gate (OQ.12 / PLAN-duckdb-pin-bump-1-5-4) ===")
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    floor_surfaces = 0
    read_surfaces = 0
    try:
        import re as _re  # noqa: PLC0415

        # (a) requirements.in floor check, then the compiled requirements.txt pin against it
        try:
            import scripts.sync.ducklake_version as _sdv  # noqa: PLC0415

            ok = _sdv.sync(check_only=True, requirements_path=_common.ROOT / "requirements.in")
            floor_surfaces = 1
            if not ok:
                failed.append(
                    "ducklake-version-lockstep: requirements.in duckdb floor drifts from "
                    "config/lambda/ducklake/version.yaml -- run: bin/venv-python -m scripts.sync.ducklake_version"
                )
                print("  FAIL: requirements.in duckdb floor drifts from the SSOT.")
            else:
                print("  PASS: requirements.in duckdb floor matches the SSOT.")
                _check_compiled_pin_satisfies_floor(failed)
        except Exception as exc:
            failed.append(f"ducklake-version-lockstep: requirements check raised: {exc}")

        # (b) no hardcoded version literal in derive surfaces
        derive_surfaces = [
            _common.ROOT / "src" / "common" / "ducklake_runtime.py",
            _common.ROOT / "scripts" / "build_lambda.py",
        ]
        for surface in derive_surfaces:
            try:
                text = surface.read_text(encoding="utf-8")
            except OSError as exc:
                failed.append(f"ducklake-version-lockstep: cannot read {surface}: {exc}")
                continue
            read_surfaces += 1
            # Allow version-looking strings in comments only if they look like semver but NOT as
            # a string assignment or constant value (i.e., PINNED_DUCKDB_VERSION = "x.y.z").
            literal_assigns = _re.findall(
                r'(?:PINNED_DUCKDB_VERSION\s*=\s*["\'])([\d.]+)(["\'])',
                text,
            )
            if literal_assigns:
                failed.append(
                    f"ducklake-version-lockstep: {surface.relative_to(_common.ROOT)} contains a hardcoded "
                    f"duckdb version literal assignment (PINNED_DUCKDB_VERSION = '...'). "
                    "Repoint through src.common.ducklake_version.pinned_duckdb_version()."
                )
                print(f"  FAIL: hardcoded version literal in {surface.name}.")
            else:
                print(f"  PASS: no hardcoded version literal assignment in {surface.name}.")
    finally:
        # Single terminal declaration (registry is last-call-wins): the requirements.in floor plus
        # every derive surface actually read. In `finally` so that an unexpected exception anywhere
        # above -- e.g. a derive surface that is not decodable UTF-8, which is a ValueError and so
        # escapes the OSError arm -- still leaves exactly one accounting declaration (Decision 170:
        # EVERY exit path declares).
        registry.examined(floor_surfaces + read_surfaces, unit="ducklake_derive_surfaces")
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def _check_compiled_pin_satisfies_floor(failed: list[str]) -> None:
    """Assert the compiled requirements.txt duckdb pin satisfies the requirements.in floor."""
    from packaging.requirements import Requirement  # noqa: PLC0415
    from packaging.version import Version  # noqa: PLC0415

    floor = _sole_duckdb_line(_common.ROOT / "requirements.in")
    pin = _sole_duckdb_line(_common.ROOT / "requirements.txt")
    if floor is None or pin is None:
        failed.append("ducklake-version-lockstep: no duckdb line in requirements.in or requirements.txt")
        print("  FAIL: duckdb line missing from requirements.in or the compiled requirements.txt.")
        return
    pinned = Version(str(Requirement(pin).specifier).lstrip("="))
    specifier = Requirement(floor).specifier
    if pinned not in specifier:
        failed.append(
            f"ducklake-version-lockstep: compiled requirements.txt pins duckdb=={pinned}, which the "
            f"requirements.in floor duckdb{specifier} rejects -- recompile with: "
            "pip-compile --strip-extras --output-file=requirements.txt requirements.in"
        )
        print(f"  FAIL: compiled duckdb pin {pinned} does not satisfy the requirements.in floor {specifier}.")
    else:
        print(f"  PASS: compiled duckdb pin {pinned} satisfies the requirements.in floor {specifier}.")


def _sole_duckdb_line(path: Path) -> str | None:
    """Return the bare duckdb requirement line (comment-stripped) from a requirements file."""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line.startswith("duckdb") and not line.startswith("duckdb-"):
            return line
    return None
