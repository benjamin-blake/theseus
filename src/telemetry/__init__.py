"""The plane-neutral telemetry kernel (Decision 199, rec-4024 slice 1).

Normative spec: docs/contracts/telemetry-event-envelope.yaml. Runs in the Lambda and against a
local DuckLake file catalog alike (Decision 184 cl.2 port rule) -- this package's runtime imports
are stdlib only (duckdb is imported under TYPE_CHECKING in append.py only). Nothing is re-exported
here: the write boundary is reachable only as src.telemetry.append.append_events, for the future
writer verb (rec-4024).
"""
