"""Verification harness (V3 integration gates), Decision 104."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_verification_harness", owner="platform")
def validate_verification_harness(failed: list[str]) -> None:
    """Run all registered programmatic verifiers (V3 integration gates).

    Declares examined over the verifiers that rendered a verdict (unit "verifiers"); a SKIPPED
    result is not counted. An empty verifier registry declares examined(0). When every verifier
    that ran reported SKIPPED, the check declares skipped() rather than an empty domain.
    """
    print("\n=== Verification Harness (V3) ===")
    try:
        import asyncio
        import sys

        # Ensure repo root is in sys.path so scripts.verifiers resolves
        root_str = str(_common.ROOT)
        injected = root_str not in sys.path
        if injected:
            sys.path.insert(0, root_str)
        try:
            from scripts.verifiers import VerifierSeverity, VerifierStatus, run_all_verifiers

            results = asyncio.run(run_all_verifiers())
        finally:
            if injected and root_str in sys.path:
                sys.path.remove(root_str)

        has_fail = False
        judged = 0
        for res in results:
            status_str = f"[{res.status}]"
            # res.severity is an enum; we want its name for display
            print(f"  {status_str:<10} ({res.severity}) {res.name}: {res.message} ({res.duration_ms:.1f}ms)")
            if res.status != VerifierStatus.SKIPPED:
                judged += 1
            if res.status == VerifierStatus.FAIL and res.severity.rank >= VerifierSeverity.HARD_GATE.rank:
                has_fail = True

        if results and judged == 0:
            registry.skipped(f"all {len(results)} registered verifier(s) reported SKIPPED")
        else:
            registry.examined(judged, unit="verifiers")

        if has_fail:
            failed.append("Verification Harness")
    except Exception as exc:
        print(f"  [ERROR] Verification harness failed to run: {exc}")
        failed.append("Verification Harness")
