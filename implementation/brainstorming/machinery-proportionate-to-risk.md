# Machinery proportionate to risk

Status: proposal. Not canon or implementation authority.

Baseline: the current merge-surviving implementation is
`../milestone_orchestrator_impl`; this proposal targets the version left when
its Brainstorming work is completed or superseded.

**Intent: every worker act that can introduce machinery into a candidate
or approve a candidate that contains it must show that it reuses what
already exists, is the cheapest option that satisfies the authorised
need, and is proportionate to realistic omission harm and exposure
unless an independent authority explicitly requires the costlier
trade-off.**

## One machinery check per change

The check belongs to one coherent change, not to each file or document:

1. **Need:** who or what is harmed without the change, the concrete harm,
   and its realistic exposure.
2. **Existing surfaces:** what code, contracts, dependencies and approved
   platform surfaces were checked; what can be reused or extended.
3. **Cheapest sufficient option:** including documentation,
   configuration or doing nothing; choose it and explain why any still
   cheaper option would not satisfy the authorised need.
4. **New machinery:** what remains to add, the independently authorised
   requirement or outcome it serves, and the authority for it.
5. **Cost:** build, migration, operation and maintenance, weighed against
   the omission described above.

If the change introduces no machinery, the answer simply names what was
checked and says so. A downstream act receives the upstream account as
context, does not re-answer it, and answers only for machinery introduced
or changed by its own delta. The governing design remains the authority.
Document reviews verify accounts carried by documents; the immediate
review of an implementation or code fix verifies its result-note account.
Later code reviews apply the same test to the candidate without demanding
or creating another account.

## Authority and enforceability

Pinning a fact or guarantee does not itself authorise an enforcement
mechanism.

- If an existing mechanism enforces the guarantee, cite and reuse it.
- If an independent governing authority requires the guarantee and no
  mechanism exists yet, record a viable, testable enforcement obligation
  as new machinery at the document's normal altitude. Pin a mechanism
  only when it is itself a public or cross-slice contract. The new
  machinery must pass the machinery check.
- If the requirement exists only because the artifact invented it, or
  it is stricter than comparable accepted work without a goal demand,
  remove or weaken the requirement instead of building for it.
- If the governing authority requires the guarantee but no viable
  mechanism can enforce it, report a design gap; do not write a promise.

Outside an explicitly reopened document set or an allowed own-note
correction, sealed documentation remains the authority. If an
implementation or fix would have to change it, do not self-authorise:
report a gap where that act is eligible, otherwise stop through its
existing blocked, repair or operator route.

## Use the surfaces that already exist

| Act | Required behaviour |
|---|---|
| Skeleton draft | Keep the existing full Question Battery and its mechanical draft validation. Clarify the existing descriptions: `victim` includes harm and exposure; `machinery` names its authority; `cheaper_alternative` chooses the cheapest sufficient option; `cost` is weighed against omission; and `enforceability` distinguishes the cases above. Add no IDs. Show reviewers the descriptions, not only their IDs. |
| Slice-note draft | Inherit the skeleton battery. Under reform, extend the existing `Reuse Posture` section with the check for machinery introduced by this slice, and let the existing `reuse_posture` battery answer point to that account. Add no parallel battery rows or repeated prose. |
| Re-documentation wave | Treat the reopened skeleton and all sealed notes as one change. Re-evaluate the skeleton's full battery once for the set; that is the single wave account, judged by review rather than a new fix-output validator. Result notes may point to it but must not duplicate it. Update each document's `Reuse Posture` only where its local claims change. Give the re-documenter the current profile's document-authoring and slice-content rules, assembled for the set without drafter-only scope or nested-gap instructions. Give its delta review the complete question descriptions. The documents under repair are questions, not defaults; authorities outside the wave remain settled. |
| Document fix | Update the target's existing Question Battery or `Reuse Posture` when the fix changes its machinery account. Its result notes may point to that document but do not duplicate it; the delta review receives the relevant descriptions. |
| Implement or code fix | Inherit the governing design and apply the check only to machinery introduced by the actual delta. On success, record the compact answer in the existing result notes and render it, as a claim rather than authority, into the first independent review of those exact bytes: an unchanged implementation goes to full review; a fix goes to its delta review. Do not carry stale notes across an intervening change. Later reviews apply the same rubric to the resulting candidate without demanding another account. If there is no new machinery, say so. |
| Rethink continuation | Repeat the reform-gated rules for the originating act when its worker resumes: the delta check for implementation or code fix, the document-account rule for a document fix, and the set-level rules for a re-documentation wave. Do not rely only on the earlier prompt. |
| Full review and delta review | Apply the same check to machinery in the target or delta. A missing or hollow document account, or immediate result-note account, is a finding when new machinery exists; later code reviews judge the machinery itself rather than historical notes. The reviewer independently verifies every claim. The seal is derived from clean same-evidence full reviews and adds no worker. This does not suppress a valid defect or prescribe its remedy. |
| Brainstorming | Apply the check before proposing or accepting machinery. Use the existing closing-summary fields as one account: affected parties and damage price omission; proportionality records the proposed machinery and authority, checked surfaces, cheapest alternative and construction cost. Render the complete summary into every vote prompt while keeping the vote response exactly `accept` or `object`. |

## Boundaries

- Keep the structured Question Battery document-only, with its current
  IDs and validation. Do not add a battery to implementation or fixes,
  or an additional battery or question rows to slice notes or documents
  in a wave.
- Under reform, successful implementation and code-fix result notes carry
  the compact answer, including a one-line `none` when no machinery was
  introduced. Review judges it; it gains no new machine-validated shape.
- Add no new act, artifact, store, ledger, profile dial, scale, closing
  field or vote field. Reuse existing document sections, result notes,
  review inputs and closing summary.
- Gate milestone-run prompt changes on the governing reform profile.
  `legacy` and profile-less runs remain byte-identical. Standalone
  Brainstorming has no such profile and tightens its existing common
  check for every session.
- Reform coverage and permission to emit a gap are separate. A
  re-documentation wave still receives the reform rules even though an
  under-repair writer may not open a nested gap.
- Proportionality constrains machinery and remedies. It does not lower
  finding severity, hide a real defect, or forbid a reviewer from
  explaining the mechanism behind one.
