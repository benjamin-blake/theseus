"""Plane-neutral Claude Code transcript producer core (telemetry slice 3a, rec-4026, T3.20).

Stdlib only, plus src.telemetry.timestamps: nothing here calls the write boundary, derives an id or
touches the network -- producers send refs, never ids (Decision 199). Nothing is re-exported: import
the submodules directly. The hooks and the writer-verb wiring are slice 3b.
"""
