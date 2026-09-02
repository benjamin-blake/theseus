# Audit: human-decision burden in the planning workflow (735e69fc)

Executive layer for `audits/planning-decision-burden-735e69fc.yaml`, which is the record. Audited
tree: `origin/main` at `735e69fc`, one commit past the prompt's anchor `939eb789`; the only file
that differs is the audit prompt. Nothing was implemented, filed, or edited outside the two
deliverables.

## What to do, in order

1. **Tag critique findings** (B3-R5): the critic tags every finding `mechanical` or `judgement`,
   with a stable anchor, generalising its existing Finding-Origin Attribution line. One byte on a
   7-byte-headroom skill; the same PR carries PDB-02's two clauses.
2. **Write down the cap procedure the human already dictates** (B3-R2): fix the mechanical set,
   run `validate --pre` before every re-dispatch, and escalate disputed judgement residue in a
   pinned shape whose menu carries the choices the human actually uses (rec-2802 names the
   dispatched-author carrier).
3. **Make the third REVISE a notice, not an interrupt** (B3-R3): when every finding is addressed
   the planner runs one confirming round itself; a REVISE at round 4, a recurrence (same critic
   tag and anchor), or round 5 brings the human back, and past 5 every round is individually
   human-authorized. The gates line records the round and an `autonomous` marker, regex-parseable.
   Closes rec-2944 with a corrected diagnosis.
4. **Narrow the Fable consult at the cap to contested residue** (B3-R1): it fires only when the
   planner disputes a surviving judgement finding, attaches a recommendation, and decides nothing;
   it demotes to discretionary if ten escalations show it changing nothing.
5. **Add `followon_recs` to the plan schema** (B1-R5), mirroring `bundled_recommendations`.
6. **File the deferred half as a follow-on-tagged rec at close-out** (B1-R1): `/implement` Step
   8/9, or `/plan` Step 8 for a planning-time split.
7. **Let preflight compute readiness and `/orient` render the prompt** (B1-R4): a follow-on rec
   whose parent plan has landed appears as a paste-ready `/plan rec-NNNN: <title>` line in Section
   6, capped.
8. **Render the ad-hoc lane** (B4-O1) in that subsection from three sources: follow-on recs, open
   Critical recs that are not ci-rca (two today, rec-3054's ask), and the priority queue (empty
   until T4.3).
9. **Extend the decision-scout with a roadmap projection** (B2-R5): intersect the Scope list with
   every tier_item's `files_in_scope`, read only those items, add a ROADMAP section with a yield
   counter that demotes to a pointer list after 40 plans with no CONFLICT.
10. **Port the autonomy-boundary policy to Step 6b** (B2-R4): forks meeting all four criteria,
    with "settled" re-read as repo precedent (a Decision, a contract, or a fork the human answered
    before; never an earlier autonomous choice), and not always-ask are decided, recorded on one
    context line and shown as notices; every other fork asks, in the `AskUserQuestion` shape
    (dispatched authors: the GATE_REQUEST hand-back).
11. **Count prior ci-rca deferrals** (B5-O1, instrumentation only): preflight annotates each
    unresolved ci-rca rec with how many merged plans deferred it, the owner they named, and
    the verdict of T3.8's shipped relevance engine, which today is never called on that path; at
    three, `/orient` turns it into the existing verify-and-close prompt. Unresolved (see method
    notes): the probe must run from that prompt, not inside preflight.

All eleven are dependency-ordered (`sequence_position` 1-11). No prose budget is raised: the two
capped skills are funded by trade-outs and one relocation counted toward rec-3378 (T2.56 c1); the
rest lands in contracts, commands and code.

## The three burdens in plain words

**B1, plan-scope splits: CONFIRMED (critical, observed).** When a session splits a plan, the
second half lands in free-text context or an untagged rec, and nothing reads it: `/orient` reads
only the preflight cache and the roadmap, and `/plan` finds a rec only when the human's own words
match it. The corpus shows the loss: a fork-B backlog recovery from July, after T-1.23 landed,
with no successor anywhere; a human-gated post-deploy half left with no tracked artefact for five
weeks (rec-3091); halves filed as recs by implement sessions (rec-3078, rec-3232) that no surface
presents. The t014 case predates T-1.23 and is baseline, not evidence; so is the pattern census
(65 of 105 matches open). Decision 115 is not tripped: the half already sits in the plan YAML, the
store it prescribes; what is missing is a key and a reader.

**B2, design forks: PARTIAL.** Presentation depth (B2a) is partial, not indeterminate: one plan
records three shaped fork lines, two of them forks any consistent choice would satisfy, and 64
plans record a human ruling, but nothing records the depth of what was shown. Roadmap-alignment
risk (B2b) is a traced gap with no observed loss: the scout's corpus is decisions only, the critic
reads only the tier_items the plan names, and the one roadmap check that exists is skipped for the
36 percent of plans claiming no tier_item. A mandatory Fable consult before every open question is
rejected: it already exists at discretion on 34 plans, and a repo-internal consistency fork poses
no industry question.

**B3, gate non-convergence: CONFIRMED (medium, observed).** All three convergence rules are count
caps; the report-critique rule is not trajectory-based, contrary to rec-2944. 34 plans record
reaching the cap, 16 in gates lines the regex cannot parse. The human's disposition is legible on
32 and takes two forms: continue (20), or accept at the cap with the round-3 fixes applied and
never re-critiqued (12). Of the twenty continuers, twelve reached PROCEED (seven on the very next
round), six accepted a terminal REVISE at rounds 4-5, two are pending; one records the human
choosing "one confirming round" and PROCEEDing at 4. The skill's menu names accept-with-deferral
and omits continue; the command's menu differs again. One candidate recurrence is recorded, a
judgement finding that survived three rounds of fixes; no oscillation between states is.

## What the human stops deciding

Removed: remembering the split half; adjudicating consistency-only forks that have a repo
precedent; the round-3 "continue" authorisation and the classification that precedes it. Added:
two reshapings of decisions the human already makes (a pick among at most four shaped options per
fork that still asks; a disposition of contested residue with a third reading attached) and two
new but rare ones (a glance at decided-with-notice lines inside the existing Step 6b turn; a
decision at round 5, or on a recurrence). Net: reduces. Runtime on the common path: zero new
dispatches, plus one autonomous confirming round on the accept-at-cap plans. Nothing removes the
Step 6b confirmation, any always-ask fork, the accept-at-cap option when residue is disputed, or
the human's authority over every round past 5; every moved authority names its revocation evidence
in the YAML.

## Sunset conditions

- B1-R1's close-out rendering and B1-R4's readiness prompts retire when the executor pulls from
  the rec queue (CD.17 reversal, T4.3 live); the `/orient` subsection persists as the queue lane
  B4-O1 renders, and the tag, the preflight key and the `followon_recs` field survive (the field
  becomes a column at T4.5).
- B5-O1 retires when Decision 73's planning-queue block stops routing ci-rca deferrals through a
  human `/plan` session (CD.17 reversal); the fixed-but-open case it instruments closes earlier
  when T3.9 lands.
- B2-R4, B3-R2, B3-R3 and B3-R1 need persona equivalents: the plan_agent autonomy clause (T4.10a),
  T4.11's loop budgets, and critic-authored verdicts at the critique gate (T4.16 c4).
- B2-R5, B3-R5 and B4-O1 survive unchanged.

## Findings that most change the picture

- **PDB-01 (critical, observed, planned-insufficient against T-1.23 and rec-3091)**: the split
  half has no typed record and no reader. T-1.23 stops at criterion grain; rec-3091 asks for the
  same shapes for post-deploy halves. Critical rests on fork B being committed work, as its plan
  states; read as optional, it is high.
- **PDB-03 (medium, observed)**: Step 6b has no shape or classification rule.
- **PDB-05 (medium, observed, planned-insufficient against rec-2944 and rec-2802)**: count caps,
  two disagreeing menus, no procedure, no dispatched-mode carrier.
- **PDB-06 (medium, observed, unnamed burden B5, planned-insufficient against T3.9 and T3.8)**: a
  ci-rca rec whose fix merged without a Resolves trailer stays open, drops out of the
  likely-resolved signal after five main commits, and is re-deferred on every later plan: rec-3292
  and rec-3293, fixed the day they were filed, were deferred eight times in six days while T3.8's
  engine, which would have said "satisfied", sat unwired. The human turn is habit on a workflow
  gap, so B5 is PARTIAL.
- **PDB-04 (medium, static, planned-insufficient against T-1.21)**: neither gate reads the roadmap
  for unnamed items; T-1.21's Freshness Gate is scoped to the named item.
- **PDB-02 (low, observed)**: the critic suggests splits for IMPLEMENTATION plans through its
  template while its question set never asks; the deferred half's disposition is unstated.

Six findings, no padding: two novel, four owned by an item whose remedy is insufficient. Maturity:
S3 frontier; S5 and S7 strong (one missed checklist row each); S1/S2/S4/S6 solid (PDB-01 is shared
across the four).

## Method notes

- Sample: 20 plans (all 12 four-or-more-round plans; 4 genuine splits naming no other plan; 2
  naming one; 2 placeholder gates lines) and 12 recs (6 oldest, 6 youngest of the 65). Not
  truncated. Out-of-sample artefacts, unpinned census methods, corpus figures and an id legend are
  in `meta.contract_notes`.
- Corpus re-derived and matching the prompt exactly (366 plans, 64 at schema 4, 243 gates lines,
  34 placeholders, the pinned histogram, 35 split-pattern hits, 16 slugs). Rec counts moved with
  the cache (874 open, not 872; 65 pattern matches, not 64); eleven stale anchors are listed in
  `meta.stale_anchors`, none changing a verdict.
- `degraded_dedup: false`; `validate --pre` not run (advisory; the deliverables are an exempt
  class); every anchor re-derived from the tree.
- Self-verification: four verifier lanes dispatched fresh each round. Rounds 1 to 3 returned
  REVISE and every finding was worked into the next revision; round 4, run after the third
  revision, still returned REVISE on two lanes (R1 cold reader, R3 challenger), so the
  three-revision cap bound and revising stopped. All 27 round-4 findings are recorded verbatim in
  `meta.self_verification.unresolved_findings`, and the confidence of the five findings and ten
  remedies they touch is downgraded to HYPOTHESIS (PDB-04 and remedies B1-R2, B1-R3, B2-R1, B2-R3,
  B3-R2, B3-R4 stay CONFIRMED). The one blocking item: B5-O1 as written would run rec acceptance
  commands inside preflight, against the surfacing-only rule at
  `scripts/preflight/correlation.py:173` (Decision 55); the fix the challenger names is to run
  T3.8's probe where the human already acts, the `/orient` verify-and-close prompt, and leave
  preflight to count. Read item 11 with that correction.
