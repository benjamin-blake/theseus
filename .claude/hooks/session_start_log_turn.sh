#!/usr/bin/env bash
# SessionStart capture pin hook (PLAN-telemetry-capture-hooks rule HK-2).
#
# Registered as `bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start_log_turn.sh" --project-ref=<ref>` on every
# SessionStart source (startup, resume, clear, compact, fork). Its exit-0 stderr line makes Claude Code record a
# SessionStart hook attachment whose command carries --project-ref=<ref>; src/turn_capture/transcript.py's
# project_ref_pin reads the pin from that attachment. It reads no stdin, touches no state and never starts a capture
# pass, so a fork is first captured only after its own fork attachment exists. Nothing on stdout (that becomes context).
printf '%s\n' "[session_start_log_turn] capture pin" >&2
exit 0
