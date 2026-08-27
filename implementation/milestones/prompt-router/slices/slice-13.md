# Slice 13 — Checkpoint cadence and failure cycle

## Outcome

Complete the scheduled suite-checkpoint lifecycle introduced by Slice 12.
Run one direct checkpoint after every fourth completed logical implementation
slice and at milestone close; when both reasons coincide, run only the final
checkpoint. A failed checkpoint becomes one dedicated full-suite fixer episode and
assigns that fixer the failed checkpoint's complete command plan. Its `ok`
certifies that the plan passed on its final workspace bytes; clean later reviews
reuse that proof instead of executing another checkpoint.

Schema activation, rejection of old runs, and physical deletion of retired
verification lanes remain Slice 14 work.

## Cadence

- Documentation and intermediate implementation parts never count or trigger.
- Only the final implementation part closes and counts one logical slice.
- A stable `passed` or `no_suite` checkpoint anchors cadence only after its
  owning slice closes.
- Count distinct completed logical slices after the latest surviving anchor.
- The fourth completed logical slice requires `four_slice_checkpoint`.
- The milestone's final implementation slice requires `milestone_final`.
- A coincident fourth/final boundary produces exactly one `milestone_final`
  call.
- Reconciliation invalidation removes any checkpoint anchor owned by an
  unwound slice. Rebuilt work is counted from the latest surviving anchor.

The existing immutable verification and slice-close events are the cadence
authority. Do not add a pending counter, generation, cache, or second cadence
store.

## Failed checkpoint

For one accepted unchanged `failed` result:

1. Keep its verification event and complete `failure_account` unchanged.
2. Queue exactly one synthetic P1 finding for the dedicated routed fixer. The
   queue entry contains that same `failure_account` verbatim; the driver does
   not parse or reinterpret its diagnostics.
3. The finding bypasses rating, debt, and reclassification and returns to the
   current unit's pre-seal checkpoint boundary.
4. The fixer may apply a repair or confirm that a transient failure is now
   clear. It runs the preserved complete command plan and returns `ok` only
   after that plan passes on the final workspace bytes; it never returns or
   corrects `suite_command`.
5. Ordinary delta review, commit discipline, and whole-artifact review apply
   when the fixer changes the candidate. An honest rejection with no delta
   closes the fixer episode normally.
6. The fixer's `ok` becomes exact-byte, exact-command verification evidence.
   The next eligible pre-seal boundary reuses it when it still matches; any
   later byte or configured-command change makes a fresh direct checkpoint call.

Either that matching fixer proof or a later stable unchanged `passed` or
`no_suite` result satisfies the due checkpoint. `blocked` remains terminal to
the operator.

## Runtime cut

| Surface | Slice 13 rule | Deferred owner |
|---|---|---|
| Cadence | every four completed logical slices and milestone final; final wins coincidence | — |
| Anchor | stable success plus later slice close; reconciliation barriers invalidate unwound anchors | — |
| Failure queue | one P1 carrying the complete checkpoint `failure_account` | — |
| Fixing | dedicated full-suite mode on the routed fixer, plus ordinary delta/review lifecycle | — |
| Suite ownership | the checkpoint discovers/runs the initial plan; its dedicated fixer runs and certifies that preserved plan after failure | — |
| Historical state | unrelated legacy `suite_command`, certification, and pending flags cannot satisfy or configure the checkpoint | deletion: Slice 14 |
| Activation | unchanged in this slice | Slice 14 |

## Verification

Focused tests must prove:

- fourth-slice, final-slice, and coincident fourth/final cadence;
- split implementation parts count exactly once, at their final part;
- stable `passed` and `no_suite` anchor cadence only after closure;
- a failed account is copied unchanged into one synthetic P1 and enters the
  ordinary fixer without rating or reclassification;
- both a fixer repair and a clean flaky rerun may certify the exact final bytes
  without another checkpoint;
- changed bytes or configured commands invalidate that proof and require a
  fresh checkpoint;
- reconciliation invalidates an unwound checkpoint anchor and rebuilt work is
  counted correctly;
- no due unit seals until a matching fixer proof or stable unchanged checkpoint
  succeeds.

## Explicit non-goals

No schema activation, compatibility lane, suite execution by the driver,
diagnostic parser, semantic classifier, inferred retry, command cache,
recovery store, backup, or protection against malformed replies, provider
failure, arbitrary repository damage, or model misbehavior. Existing declared
contract correction and terminal boundaries remain unchanged.
