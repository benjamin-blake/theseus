#!/usr/bin/env python3
"""Run a zero-context programmatic LLM call using a skill definition.

This script enforces a fresh context window for critical agentic tasks like
critiques, preventing cognitive bias by passing the instructions and target
content to a fresh API call.
"""

import argparse
import sys
from pathlib import Path


def resolve_context_paths(explicit_context: list[str] | None) -> list[str]:
    """Order-preserving de-duplication of explicitly-supplied --context paths.

    Context injection is explicit-only: the retired frontmatter auto-loading primitive
    is gone, so every caller names the context files it needs via --context (see
    docs/contracts/instruction-architecture.yaml layer-4).
    """
    paths: list[str] = []
    for c in explicit_context or []:
        if c not in paths:
            paths.append(c)
    return paths


# Add root to sys.path to allow running directly from CLI
ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.llm.client import llm_call  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an isolated agent skill against a target file.")
    parser.add_argument("--skill", required=True, help="Name of the skill in .claude/skills/")
    parser.add_argument("--target", required=True, help="Path to the target file to evaluate")
    parser.add_argument("--model", help="Optional model override")
    parser.add_argument(
        "--context",
        nargs="*",
        help="Explicit context-injection path(s): repo-relative file(s) loaded into context (e.g. docs/PROJECT_CONTEXT.md).",
    )
    args = parser.parse_args()

    skill_path = ROOT / ".claude" / "skills" / args.skill / "SKILL.md"
    if not skill_path.exists():
        print(f"Error: Skill file not found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    target_path = ROOT / args.target
    if not target_path.exists():
        print(f"Error: Target file not found at {target_path}", file=sys.stderr)
        sys.exit(1)

    # Load the pure instructions from the skill file
    system_prompt = skill_path.read_text(encoding="utf-8")

    all_context_paths = resolve_context_paths(args.context)

    context_text = ""
    if all_context_paths:
        context_text += "\n\n## Additional Context\n"
        for cp in all_context_paths:
            p = ROOT / cp
            if p.exists():
                context_text += f"\n### File: {cp}\n{p.read_text(encoding='utf-8')}\n"
            else:
                print(f"Warning: Context file not found: {cp}", file=sys.stderr)

    # Build the target context
    user_prompt = (
        f"Please execute your skill instructions against the following file.\n\n"
        f"File: {args.target}\n\n"
        f"Content:\n{target_path.read_text(encoding='utf-8')}"
        f"{context_text}"
    )

    print(f"Running skill '{args.skill}' against '{args.target}' in a fresh context...", file=sys.stderr)

    # We pass the skill content as both inline_instruction (for Gemini)
    # and system_prompt (for Bedrock) to perfectly cover both providers.
    result = llm_call(
        prompt=user_prompt,
        system_prompt=system_prompt,
        inline_instruction=system_prompt,
        purpose=f"skill_{args.skill}",
        model=args.model,
        tools=True,  # We enable tools so the agent can agentically read the workspace
        check=False,
    )

    if result.exit_code != 0:
        print(f"\nLLM Error (exit {result.exit_code}):\n{result.stderr or result.content}", file=sys.stderr)
        sys.exit(result.exit_code)

    print("\n" + "=" * 50)
    print(f" {args.skill.upper()} OUTPUT ".center(50, "="))
    print("=" * 50 + "\n")
    print(result.content)
    print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    main()
