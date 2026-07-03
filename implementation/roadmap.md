# Implementation Roadmap Canon Roadmap

## Goal

Maintain a small, reusable implementation-roadmap canon that product
repositories can pin by Git revision while keeping their live roadmap state
local.

## Current State

`v0.1.0` exists as the initial unreviewed bootstrap release. S0 brought this
repository under its own process by adding local state, reviewing the initial
canon and templates, fixing findings, and publishing `v0.1.1` as the first
reviewed release.

S1 made the doubt, disagreement, cross-model consultation, adjudication, and
finding-verification protocol explicit, and publishes it as reviewed release
`v0.2.0`.

S2 moved common process rules proven in Agent99 and Tutor into the common canon
while keeping live project state local. It adds required local context,
non-canonical planning-material boundaries, broad reviewer invocation, and seal
reviewer independence as reviewed release `v0.3.0`.

S3 reduces review latency without weakening evidence. It makes local checkout
inspection explicit for reviews and requires concurrent double-seal launch when
possible as reviewed release `v0.4.0`.

S4 adds milestone planning cost controls as reviewed release `v0.5.0`: thin
skeletons, just-in-time slice notes, small reviewable slice diffs, compact
durable review logs, and resumable CLI quota pauses.

S5 adds the review/seal convergence formula as reviewed release `v0.6.0`:
Codex CLI reviews run clean first, Claude CLI reviews run clean second, full
official verification brackets review, and later seal findings return to the
full seal round unless the fix materially changes scope or design.

S6 adds phase-gate logging as reviewed release `v0.7.0`: normal review clean
states must be recorded as explicit durable gates before seal opens, and
Claude-phase fixes must not drift back into normal Codex rounds.

## Next Direction

Open future canon changes as new milestones. Keep consuming product
repositories pinned to reviewed tags.

## Non-Goals

- Store product roadmap status in this repository.
- Rewrite the already-published `v0.1.0` tag.
- Add automation before the manual canon is reviewed.
