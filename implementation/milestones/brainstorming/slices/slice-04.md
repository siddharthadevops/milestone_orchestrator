# Slice 04 — Plain-language session transcript

## Register 1 — Intent

### What this slice builds

This slice gives every brainstorming session one readable account of what the
group was trying to decide, who spoke, what they said, what materially
interrupted the discussion, how each closure ballot went, and how the session
ended. A person can follow that account without understanding the service,
agent tooling, or diagnostic logs.

The account starts before anyone speaks, grows only from accepted session facts,
and always ends with a plain closing explanation. A failed session still tells a
complete story when it ends before the first participant finishes a turn.

### Ownership and boundary

This slice owns the human account and its stable session reference. It turns the
accepted request, participant order, completed discussion, explicit material
interruptions, accepted closure ballots, and terminal summary into one ordered
Markdown artifact.

It does not decide whether a participant turn is accepted, whether agreement
has been reached, or whether the session succeeds. The transition owner decides
whether an interruption materially changed or stopped discussion: this slice's
coordinator for participant-supervision outcomes, Slice 5 for closure outcomes,
and Slice 6 for an explicit stop. Slice 4 owns their common durable append and
never infers an interruption from diagnostics. It does not expose a route or
screen and does not connect a product.

### Guarantee posture

- **Strict:** one session has one stable human account; its opening is first,
  accepted turns appear once and in order, explicitly recorded material
  interruptions and accepted closure ballots keep their position, every ballot
  records every human-labeled vote and its applied rule, and a terminal session
  has exactly one complete closing entry. A completed update never reports a
  newer account than durable session state or publishes a losing concurrent
  update.
- **Optimistic:** concurrent writers contend on the durable session revision.
  A stale writer may retry from the winner, but it cannot duplicate, reorder, or
  replace accepted transcript progress.
- **Eventual:** none. The later visualization may refresh eventually, but this
  artifact is the transcript authority exposed by its reference.
- **Best-effort:** the service preserves accepted participant-authored Markdown;
  it does not rewrite a participant's prose for style. The strict plain-language
  boundary covers service-authored entries and prevents automatic copying of
  machine identifiers, telemetry, and raw diagnostics.

### Dependencies and consumers

The slice depends on the immutable request and participant roster, the durable
session lifecycle, and the ordered accepted-turn projection. The coordinator
must publish each newly accepted turn before reporting that turn complete.

The next closure slice supplies each accepted ballot and the terminal summary
without changing transcript ordering. This slice's coordinator produces and
appends a human-safe interruption when participant supervision materially
changes or stops discussion; Slice 5 closure and Slice 6 stop handling produce
and append their own such interruption through the same contract. The later
lifecycle interface returns the transcript reference, and the later
visualization reads the same account. Current service routes, the panel,
milestone transitions, and the read-only product roots are not consumers of
this slice.

### Non-goals

- No participant execution, turn acceptance, target revision creation, vote
  collection or counting, closure decision, or terminal-outcome decision.
- No public API route, event stream, visualization, milestone signal, or
  Agent99 adapter.
- No process log, provider-session history, telemetry archive, or diagnostic
  export.
- No new permission, sandbox, work-area, target custody, or liveness system.
- No interpretation of participant Markdown or caller-native structured
  evidence.
- No modification or recovery of the target or any other caller-owned path.

### Acceptance

The slice is accepted when a session's human account is readable from its stable
reference; begins with the purpose, target, participant roles, agreement rule,
and round bound; and presents every accepted turn once in durable order with a
human label and its round.

Rejected output, repair exchanges, worker-control facts, participant and
provider identifiers, target revision hashes, telemetry, and raw diagnostics do
not become service-authored transcript content. An explicitly material
interruption appears once at the point it was recorded. Ordinary retries and
rejected work do not create transcript entries.

Every accepted closure ballot appears once at its durable position, including a
failed ballot after which discussion resumes. It identifies the target in plain
language by the completed round at which it was considered, shows each
participant's human label and `accept` or `object` vote, names the applied
closure rule, and says whether the ballot approved closure. The underlying
Brainstorming revision identifier or hash stays in structured state.

Both terminal outcomes append one complete closing account. It explains whether
agreement was reached and why, identifies the produced or unfinished target,
reports completed rounds and unresolved objections, and records the required
affected-party, realistic-damage, proportionality, and escalation-evidence
summary. The same is true when zero turns completed.

Restart and concurrent-writer checks prove that accepted entries are neither
lost nor duplicated and that a stale or interrupted publication is reconciled
from durable state before the session proceeds. Separate sessions never share a
transcript, and the target can never alias the service-owned transcript.

The implementation is expected to stay around the roughly 500 changed-line
target by deriving opening and turn entries from existing accepted state and
adding only the missing interruption, ballot, closing, publication, and
focused-test surface. A parallel transcript store or general event framework
would exceed this slice.

### Risks

- Writing an independent log can drift from accepted state. The human account is
  a deterministic projection of durable session facts and is repaired from
  those facts after interruption.
- Copying execution records can expose technical detail or rejected work. The
  projection uses an explicit human-content allowlist, including only accepted
  ballot facts rendered under human labels.
- Arbitrary supplied text can imitate headings. System entry boundaries remain
  unambiguous while accepted participant Markdown stays intact.
- A stale publisher can otherwise duplicate an entry or overwrite the closing.
  Publication follows the winning durable revision and preserves the accepted
  prefix.
- A caller target that aliases transcript storage could let target work corrupt
  the human record. Admission rejects that overlap before participant work.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Transcript identity | Each session has one stable, session-scoped `transcript_ref`; different sessions never share it and its final path component is exactly `chat.md`. The reference names Brainstorming-owned storage, not `workspace_path` or `target_path`. A target that resolves to or aliases this transcript is rejected before participant work. | `implementation/milestones/brainstorming/skeleton.md:3-5,36-47,76,98,104-105`; `orchestrator/brainstorming.py:592-613,893-903`; `orchestrator/brainstorming_coordination.py:83-123` | touch one session-scoped transcript projection and extend the existing authority-alias guard; do-not-write the transcript into caller-owned target/workspace storage |
| Entry vocabulary and order | The observable entry kinds are exactly `opening`, `discussion_turn`, `material_interruption`, `closure_ballot`, and `closing`. There is one opening first; one `discussion_turn` for each durable completed turn in the same order; zero or more explicitly recorded interruptions and one `closure_ballot` for each accepted ballot at their durable append positions; and one closing last only for a terminal session. Interruptions and ballots at the same completed-turn boundary retain their accepted append order. Published entries form an immutable prefix. | `implementation/milestones/brainstorming/skeleton.md:25-28,76-77,104-105`; `implementation/milestones/brainstorming/goal.md:230-264`; `orchestrator/brainstorming.py:423-506,811-868`; `orchestrator/brainstorming_coordination.py:701-809` | touch transcript facts and projection; do-not-project attempted, repaired, rejected, or process-control work as discussion turns or ballots |
| Opening account | Before the first completed turn, `opening` states the request `question` and `context.brief`, the target being worked on, the human participant labels with the lead identified, the selected closure policy, and `max_rounds`. `unanimity` is explained as everyone having to agree; `majority_with_lead_tiebreak` as a majority deciding with the lead breaking an exact tie. It does not copy `context.source_payload`, executor/provider references, or same-family diagnostics. | `implementation/milestones/brainstorming/skeleton.md:99-100,104-105`; `implementation/milestones/brainstorming/goal.md:194-211,243-264`; `orchestrator/brainstorming.py:285-359,639-683` | touch deterministic opening projection; do-not-interpret opaque context or expose machine assignment details |
| Turn account and human labels | `discussion_turn` shows the one-based durable round and accepted Markdown. The persisted lead is displayed as `Lead`; interlocutors are displayed as `Interlocutor 1`, `Interlocutor 2`, and so on in persisted roster order. These labels, not participant ids, executor refs, provider-session refs, or target revision hashes, identify speakers in `chat.md`. Supplied Markdown cannot escape its turn boundary or forge a service entry. | `implementation/milestones/brainstorming/skeleton.md:25-28,100,103-104`; `orchestrator/brainstorming.py:263-359,423-506,811-853`; `orchestrator/brainstorming_execution.py:133-180,276-370` | touch a human-label projection over accepted turns; do-not-add a roster field, rewrite participant prose, or expose execution metadata |
| Material interruption input and producers | The cross-slice fact is `material_interruption` with exactly `after_completed_turns` and `plain`. The first is a non-negative integer equal to the current completed-turn count when appended; `plain` is a non-empty ordinary-language string. Records are append-only. Slice 4's coordinator produces and appends this fact for a participant-supervision outcome that materially changes or stops discussion; Slice 5 does so for a closure outcome and Slice 6 for an explicit stop, through the same append contract. No exception, raw output, telemetry, participant-session reference, or target revision is accepted into this fact, and no producer infers materiality from diagnostics alone. | `implementation/milestones/brainstorming/skeleton.md:3-5,44-45,74-78,102-105`; `implementation/milestones/brainstorming/goal.md:181-183,213-216,230-241,300-316`; `orchestrator/brainstorming_execution.py:331-377`; `orchestrator/brainstorming_coordination.py:701-809` | touch one minimal durable interruption append at the coordinator's accepted-state boundary and renderer; do-not-copy repair/diagnostic records or leave production to an unnamed future component |
| Closure ballot input and account | Slice 5 supplies one accepted `closure_ballot` with exactly `after_completed_rounds`, `target_revision`, `votes`, and `approved`. The round count is a positive integer equal to durable `rounds_used`; `target_revision` equals the accepted Brainstorming target revision considered; `votes` contains every persisted participant once in roster order, each with exactly `participant_id` and `vote` equal to `accept` or `object`; `approved` is the boolean result of applying the configured policy. The account renders the round-based target description, human labels, every vote, the plain policy, and approval result. Failed ballots remain in place when discussion resumes. It never renders participant ids or the revision identifier/hash. | `implementation/milestones/brainstorming/skeleton.md:25-28,76-77,103-105`; `implementation/milestones/brainstorming/goal.md:230-264`; Operator Amendment A1, **Target versioning clarification** | touch the minimal accepted-ballot seam and renderer; do-not-collect votes, recalculate closure, expose machine identifiers, or treat ballot work as a discussion turn |
| Closing input and account | The cross-slice `closing_summary` has exactly `reason`, `unresolved_objections`, `affected_parties`, `damage_altitude`, `proportionality`, and `escalation_evidence`. `reason`, `affected_parties`, `damage_altitude`, and `proportionality` are non-empty strings; `unresolved_objections` is a list of non-empty strings; `escalation_evidence` is `null` or a non-empty string. Accepted ballots remain separate ordered entries rather than being duplicated in this summary. Terminal outcome supplies whether agreement was reached and whether the target is produced or unfinished; request/state supply target and completed rounds. On failure, `closing_summary.reason` equals `result.reason`. Missing or malformed summary, a mismatched `transcript_ref`, or absent transcript ballot evidence required by accepted closure state rejects terminalization. A terminal operation is not reported complete until its closing is published; interruption after the durable transition is repaired before terminal state is exposed again. | `implementation/milestones/brainstorming/skeleton.md:25-28,77,104-106`; `implementation/milestones/brainstorming/goal.md:117-146,218-221,243-264`; `orchestrator/brainstorming.py:592-613,639-708` | touch the minimal closing seam and terminal transcript gate; do-not-decide closure, duplicate target/round/ballot facts, add a damage taxonomy, or add caller actions |
| Durable consistency and recovery | Durable session state is the transcript source. A completed transcript-producing operation publishes one complete UTF-8 Markdown snapshot for the winning session revision before returning; a stale writer cannot publish its candidate. Atomic publication exposes the prior or next complete file, never a partial file. After interruption, the next preparation/read/terminal return reconciles `chat.md` from durable state without changing the accepted prefix or target. | `implementation/milestones/brainstorming/skeleton.md:23-34,76,92,104`; `orchestrator/brainstorming.py:711-730,1034-1054,1122-1157`; `orchestrator/kvstore.py:343-359,391-457` | touch the existing CAS/atomic-replacement patterns and coordinator completion boundary; do-not-create a second transcript authority or claim exactly-once worker execution |
| Slice boundary | Slice 4 adds no public route or error code, vote/closure policy evaluation, terminal-outcome rule, UI surface, milestone chronology, product adapter, permission rule, or target-version behavior. Existing completed-turn and discussion-envelope shapes remain unchanged. | `implementation/milestones/brainstorming/skeleton.md:36-47,73-80,102-108`; `orchestrator/brainstorming_execution.py:12-27`; `orchestrator/service.py:2735-2887` | touch transcript state/projection, its focused coordinator/terminal hooks, and tests; do-not-touch service routes, panel, milestone flow, external roots, or target recovery semantics |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_transcript`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Opening and references are session-scoped | `test_opening_precedes_turns_and_refs_are_session_scoped` | Two sessions receive distinct stable references ending in `chat.md`; each opening precedes any turn and contains the correct purpose, target, human role labels, plain closure rule, and round bound without opaque or execution-only fields. | strict |
| Accepted turns render once in durable order | `test_completed_turns_render_once_in_order_with_human_labels` | Cross-family and same-family fixtures render each durable completed turn exactly once, in roster/round order, under `Lead` or the correct numbered interlocutor label; restart preserves the same prefix. | strict |
| Control and diagnostics remain separate | `test_rejected_repairs_and_machine_details_stay_out` | Invalid envelopes, repair exchanges, rejected target mutations, attempt tokens, participant/executor/provider ids, target revision hashes, telemetry, and raw diagnostic sentinels do not appear as service-authored entries. | strict system projection; best-effort participant prose |
| Supplied text cannot forge service entries | `test_supplied_markdown_cannot_forge_entry_boundaries` | Heading-like request, target, interruption, ballot, closing, and participant text remains inside its owning entry; parsing still yields one opening, the expected ordered turns/interruptions/ballots, and one closing. | strict |
| Only explicit material interruptions append | `test_only_explicit_material_interruptions_append_in_place` | An accepted interruption at the current turn count appears once at that position; stale, backdated, malformed, repair-only, and ordinary retry facts are rejected or absent without changing the published prefix. | strict state; optimistic conflict detection |
| Accepted closure ballots tell the complete voting history | `test_closure_ballots_render_every_vote_and_failed_attempt_in_order` | Successful and failed accepted ballots appear once at their durable positions with the round-based target description, every human-labeled vote, the configured policy, and approval result; a same-boundary interruption and discussion after a failed ballot retain append order, while rejected ballot attempts, participant ids, and revision hashes remain absent. | strict |
| Every terminal path has one complete closing | `test_terminal_closing_is_complete_even_before_first_turn` | Success, failure after discussion, and failure before any completed turn each render exactly one final entry with outcome/reason, target disposition, durable rounds, objections, and contextual closing facts; the failure reason matches the result; missing/extra/malformed summaries and mismatched references cannot terminalize. | strict |
| Interrupted publication repairs from state | `test_restart_repairs_projection_without_rewriting_prefix` | Injected publication failure exposes no partial Markdown; reopening reconciles the winning durable opening/turn/interruption/ballot/closing projection before proceeding and retains prior entry bytes and order. | strict completed operations and recovery |
| Stale writers cannot publish losing progress | `test_stale_writer_cannot_duplicate_or_publish_losing_transcript` | Two writers from one revision yield one durable successor; the losing candidate never replaces or duplicates the winner in `chat.md`. | strict transcript; optimistic conflict detection |
| Transcript and target remain isolated | `test_transcript_isolated_from_target_and_current_consumers` | Target/transcript alias attempts fail before execution; ordinary target recovery leaves the transcript intact; Slice 1-3 focused suites stay green; service routes and external-root sentinels are unchanged. | strict compatibility |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:309-319`). Later slices add closure, standalone API,
visualization, and milestone-adapter checks; milestone closure retains the
matrix in `implementation/milestones/brainstorming/skeleton.md:124-137`.

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **verified current seams:** `SessionStore` owns request/config/lifecycle/result and accepted turns; `BrainstormingCoordinator` commits each accepted turn and returns its snapshot. **slice-local consumer and interruption producer:** the focused transcript suite plus the coordinator/terminal hooks that append explicit human-safe interruptions and publish the winning projection. **declared next consumers/producers:** Slice 5 supplies accepted ballots, the closing summary, and any closure-driven interruption; Slice 6 returns `transcript_ref` and supplies any stop-driven interruption; Slice 7 reads the ordered Markdown. **not touched:** current service routes, panel, milestone transitions, Agent99, Life, LPC, and Tutor. | `orchestrator/brainstorming.py:592-730,893-915,1034-1157`; `orchestrator/brainstorming_coordination.py:540-555,632-650,673-809`; `orchestrator/service.py:2735-2887`; `implementation/milestones/brainstorming/skeleton.md:73-80` |
| pinned_facts | **closed facts:** one session-scoped `chat.md` reference; five observable entry kinds and their order; derived opening; human turn labels; minimal interruption, accepted-ballot, and closing inputs; explicit coordinator ownership of interruption append; strict winning-state publication/recovery; transcript/target isolation; and no route, UI, closure decision, product adapter, or target-version change. | `implementation/milestones/brainstorming/skeleton.md:23-47,73-80,98-108`; `implementation/milestones/brainstorming/goal.md:185-264`; `orchestrator/brainstorming.py:423-506,592-708,811-868` |
| verification | **focused:** the ten named checks cover reference isolation/opening, accepted order/labels, diagnostic exclusion, entry-boundary integrity, material interruptions, accepted ballots including failed attempts, all closing paths including zero turns, restart repair, stale publication, and target/current-consumer compatibility. **full:** repository unittest discovery remains the milestone gate. | `implementation/milestones/brainstorming/skeleton.md:124-137`; `implementation/milestones/brainstorming/goal.md:336-374`; `orchestrator/README.md:309-319` |
| reuse_posture | **checked:** exact session/result validators, immutable roster, ordered completed turns, whole-state CAS, target-authority alias checks, atomic file replacement, current service routes, and focused fake-executor tests. **adopted:** accepted state as authority, existing CAS/append-only successor enforcement, atomic replacement, alias-guard pattern, and test style. **extended:** session state gains only explicit material interruptions and accepted ballots, while terminal state gains the contextual closing fact. **new-with-why:** one session-scoped Markdown projector is required because current code explicitly defers transcripts and retains only a reference, while the skeleton mandates a complete `chat.md`. | `orchestrator/brainstorming.py:1-6,263-359,423-506,592-730,811-868,893-915,1034-1157`; `orchestrator/brainstorming_coordination.py:83-123,673-809`; `orchestrator/kvstore.py:343-359,391-457`; `orchestrator/service.py:2735-2887`; `implementation/milestones/brainstorming/skeleton.md:49-67,76-77,104-105` |
| enforceability | **content/order:** immutable request/config plus validated append-only completed turns drive a closed renderer. **human boundary:** role/order labels and an allowlisted system template never read execution ids, raw results, or opaque payload; supplied Markdown is contained by entry boundaries. **interruptions/ballots/closing:** the coordinator-owned interruption append and exact validators plus append-only/CAS successors reject malformed, stale, backdated, duplicate, rejected, or incomplete facts; Slice 5 supplies closure truth while this slice projects every accepted ballot. **publication/recovery:** winning session CAS, atomic file replacement, and deterministic reconciliation prevent partial or losing projection. **isolation:** the existing authority-alias gate extends to the transcript. **excluded:** participant prose quality remains best-effort. | `orchestrator/brainstorming.py:263-359,423-506,639-730,811-868,1034-1157`; `orchestrator/brainstorming_execution.py:133-180,331-377`; `orchestrator/brainstorming_coordination.py:83-123,673-809`; `orchestrator/kvstore.py:343-359,391-457`; `implementation/milestones/brainstorming/skeleton.md:23-34,76-77,92,104-106` |

### Reuse Posture

- **Checked:** the current exact request/config/result validators, immutable
  roster, ordered completed-turn projection, whole-state CAS, target-authority
  alias guard, atomic replacement, service routes, and stateful focused-test
  style. Authorities: `orchestrator/brainstorming.py:263-359,423-506,592-730,811-868,893-915,1034-1157`;
  `orchestrator/brainstorming_coordination.py:83-123,673-809`;
  `orchestrator/kvstore.py:343-359,391-457`;
  `orchestrator/service.py:2735-2887`;
  `orchestrator/tests/test_brainstorming_coordination.py:121-176`.
- **Adopted:** the accepted session snapshot remains the only authority.
  Existing exact validators, append-only successors, revision CAS, atomic
  replacement, authority-alias rejection, and fake-executor test style are
  reused.
- **Extended:** the durable record gains only explicit material interruptions,
  accepted closure ballots, and the contextual closing summary that cannot be
  derived from existing request, roster, completed turns, lifecycle, and result
  fields. The coordinator owns the interruption append; closure supplies ballot
  facts; coordinator and terminal return boundaries publish the winning
  projection.
- **New-with-why:** one session-scoped Markdown projector is necessary. Current
  code explicitly leaves transcripts to a later slice and the existing result
  retains only a non-empty reference; neither can produce the opening,
  interruptions, turns, ballots, or closing required by the skeleton and its
  preserved closure intent.
- **Compatibility:** the discussion envelope, completed-turn shape, target
  revisions, caller context, service routes, and external products remain
  unchanged. Slice 5 supplies accepted ballots and closing facts through this
  seam rather than creating a second transcript path.

### Enforceability Gate

| invariant asserted here | mechanism that can enforce it | implementation gate |
|---|---|---|
| Stable per-session transcript identity and target isolation | `SessionStore.path` gives one service authority root (`orchestrator/brainstorming.py:896-903`); validated session ids and the existing state/lock alias guard provide the extension seam (`orchestrator/brainstorming.py:871-890`; `orchestrator/brainstorming_coordination.py:83-123`) | Distinct-session and alias fixtures prove references never collide and no participant runs when target and transcript overlap. |
| Opening is fixed and first | Immutable validated request/config and successor guards (`orchestrator/brainstorming.py:285-359,639-730`) provide every allowed opening fact and prevent later drift | Opening fixtures compare the first parsed entry before and after restart and ensure opaque/execution-only sentinels are absent. |
| Turns appear once in accepted order | The exact roster-prefix/round validator and atomic completed-turn successor (`orchestrator/brainstorming.py:423-506,811-868,1122-1157`) are the only turn source | Cross-/same-family, rejection, restart, and contention fixtures compare parsed turn entries one-for-one with durable `completed_turns`. |
| Human entry boundary excludes machine-owned records | The renderer consumes only immutable request text, role/order labels, accepted Markdown, accepted ballot decisions, and validated plain interruption/closing facts; provider refs, target-revision identifiers, and repair/raw output remain in separate structured state or execution objects (`orchestrator/brainstorming_execution.py:133-180,331-377`) | Identifier/diagnostic sentinels and heading-like inputs prove no system field is copied and no supplied text forges an entry boundary. |
| Interruptions are explicit, current, append-only, and owned | Existing exact-key/type validation and complete-state successor/CAS patterns (`orchestrator/brainstorming.py:79-118,711-730,1034-1054`) can enforce the two-field fact, current completed-turn count, prefix preservation, and one winning coordinator append; lifecycle owners supply only already-classified human-safe facts | Valid/current, malformed, backdated, repair-only, stop/closure-owner, and stale-writer matrices observe one append or none and prove no later slice or diagnostic inference is required to produce it. |
| Accepted ballots remain in the human history | Slice 5's exact accepted ballot and configured policy provide the authoritative votes and decision; roster labels and the durable round position provide the human projection without exposing participant or target-revision identifiers | Successful, failed-then-resumed, malformed, rejected, and stale ballot matrices compare each accepted ballot with one ordered account entry and prove every vote, rule, and result is visible. |
| Closing is complete, terminal, and unique | Existing explicit lifecycle/result validators and terminal append guard (`orchestrator/brainstorming.py:592-708,711-730`) can require the exact closing summary and matching transcript reference in the same terminal successor | Success/failure/zero-turn matrices reject missing, extra, malformed, duplicate, nonterminal, or mismatched closing data. Slice 5 remains responsible for truthful closure eligibility. |
| Published Markdown matches the winning durable snapshot | Whole-state CAS selects one successor (`orchestrator/brainstorming.py:1034-1054`); same-directory temporary-file replacement exposes a complete old or new file (`orchestrator/kvstore.py:391-457`); accepted-turn return is already centralized (`orchestrator/brainstorming_coordination.py:795-809`) | Injected replace failure, restart, and two-writer checks prove no partial or losing file and deterministic catch-up before the next completed return. |
| Best-effort prose is not promoted into a strict semantic claim | Slice 2 accepts one non-empty participant Markdown field and deliberately does not interpret it (`orchestrator/brainstorming_execution.py:12-27,155-167`) | Tests require exact preservation and structural containment, not subjective rewriting or a claim that arbitrary participant prose is ideal. |

If implementation keeps an independent append log, lets a transcript write race
ahead of durable state, copies raw execution objects, or relies on participant
ids as display names for a strict row, that guarantee is not delivered.

### Planning Material Disposition

- **Adopt:** the sealed skeleton as the operative boundary and the generated goal
  snapshot only for the plain opening, ballot history, and closing intent that
  the skeleton leaves with this slice's human account.
- **Revise:** existing state and file-projection patterns only into a
  Brainstorming-owned, session-scoped human artifact; they do not authorize a
  milestone log or caller-workspace transcript.
- **Reject:** all exploratory brainstorming material as independent authority,
  including older machine-API, Persona, event-cursor, or bearer-token proposals.

Authority: `implementation/milestones/brainstorming/skeleton.md:3-5,36-67,76,98,104,110-122`;
`implementation/brainstorming/README.md:3-17`.
