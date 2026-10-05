"""Project a Class A SCD2 contract's declared row rules into the field_semantics column entries (rec-4158 plan B).

scripts.contract_rules.declared_rules is the ONE reader (the live census compiles the same list), so the writer's
rule set and the census's are the same by construction. Each non-exempt leg becomes a column key the shared engine
(src/row_rules/rules.py) evaluates; a leg carrying an exemption ships only as write_time_exemptions[kind]. The enforced
flag belongs to the DQ runner and never reaches the projection (plan C owns the platform-wide re-read).
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.contract_rules import DeclaredRule, declared_rules


def _rule_value(rule: DeclaredRule) -> Any:
    params = rule.params
    if rule.kind == "accepted_values":
        return list(params["values"])
    if rule.kind == "array_element_format":
        return params["pattern"]
    if rule.kind in ("min_length", "pattern", "not_before"):
        return params["value"]
    raise ValueError(f"{rule.table}.{rule.column}: unknown rule kind {rule.kind!r} -- fail closed")


def project_row_rules(table_id: str, columns: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return *columns* with every declared rule of *table_id* merged into its column entry (inputs are not mutated)."""
    out = {name: dict(spec) for name, spec in columns.items()}
    for rule in declared_rules(table_id):
        spec = out.get(rule.column)
        if spec is None:
            raise ValueError(f"{table_id}.{rule.column}: a declared rule names a column the projection does not carry")
        if rule.exemption is not None:
            spec.setdefault("write_time_exemptions", {})[rule.kind] = dict(rule.exemption)
            continue
        if rule.kind == "not_null":
            if spec.get("nullable") is False:
                if rule.exclude_before is not None:
                    raise ValueError(f"{table_id}.{rule.column}: a dated not_null on a nullable:false column drops its date")
                continue
            spec["not_null"] = True
        else:
            spec[rule.kind] = _rule_value(rule)
        if rule.exclude_before is not None:
            spec.setdefault("exclude_before", {})[rule.kind] = str(rule.exclude_before)
    return out
