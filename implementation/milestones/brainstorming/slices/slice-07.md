# Slice 07 — Dedicated brainstorming visualization

## Register 1 — Intent

### What this slice builds

This slice gives an operator a dedicated browser view of one known
Brainstorming session. The view shows who is discussing what, the agreed run
policy, accepted round progress, whether the process is live, the discussion in
order, the accepted target, and the final result when the session ends.

The page follows durable progress automatically and lets an authorized operator
stop an active session through the lifecycle already delivered. It remains a
projection: the discussion continues without the page, and the page never
decides or records process truth.

### Ownership and boundary

This slice owns only the dedicated view and the read projection needed to render
it coherently. It consumes the standalone lifecycle, durable session state,
human transcript, accepted target versions, and result contract delivered by
the preceding slices.

It does not add session discovery, a launch form, a milestone phase, or a
product adapter. It does not place discussion turns in the milestone panel or
milestone chronology. Creation remains available through the standalone
lifecycle interface, and a caller that already has a session identity can open
this view.

### Guarantee posture

- **Strict:** every successful view read is authorized and represents one
  complete durable session revision. Its roster, policy, accepted rounds,
  ballots, transcript, accepted target, status, and result agree. Participant
  text is displayed as inert content, never executable page markup.
- **Optimistic:** a stop racing completion inherits the lifecycle's single
  durable winner. The page ignores an older response that arrives after a newer
  one.
- **Eventual:** the page polls. It can lag durable state by one normal refresh
  interval and keeps the last good revision visibly marked stale during a
  transient read failure.
- **Best-effort:** browser/network delivery and live-process observation retain
  their existing limits. This slice adds no push, exactly-once notification, or
  perfect provider-liveness claim.

### Dependencies and consumers

This slice depends on the accepted request and roster, ordered round state,
plain-language transcript, revision-bound closure and result, and the
standalone inspect/stop lifecycle.

Its direct consumer is the human operating a standalone Brainstorming session.
The local service and Brainstorming state are touched to provide the view. The
milestone panel, milestone state and routes, and the read-only Agent99, Life,
LPC, and Tutor workspaces are not changed.

### Acceptance

An authorized operator can open a stable URL for a known session and see every
required Brainstorming fact in one readable view. As accepted turns, ballots,
target versions, and a terminal result become durable, a later refresh shows
them in order without mixing revisions.

The transcript is shown as Markdown source and the accepted target is previewed
when it is text. An absent, binary, not-yet-accepted, or oversized target is
identified honestly while its reference and accepted version remain visible.

The active-session stop control uses the existing stop contract. After it
returns, the page refreshes immediately and continued polling converges on the
same terminal winner. Unknown or unauthorized sessions reveal no discussion,
transcript, or target content.

The dedicated page contains no milestone units, slices, reviews, seals, or
chronology. Existing milestone views and routes remain unchanged. The slice is
expected to stay under about 500 changed lines by reusing the existing
projection, renderer, polling, access, and stop seams.

### Non-goals

- No session collection, search, delete, restart, launch form, or recent list.
- No event cursor, long poll, server-sent event, WebSocket, webhook, or digest.
- No new transcript format, closure rule, result, target-version scheme, or
  process authority.
- No new identity, permission, sandbox, work-area, repository, or VCS policy.
- No milestone-panel conversation, milestone-ledger state, Agent99 adapter, or
  target-specific UI.
- No arbitrary binary viewer, editor, target mutation, or raw diagnostic view.

### Risks

- A projection assembled from different reads could pair an old transcript with
  a new result. The view succeeds only from one durable session revision and
  its referenced immutable target version.
- Participant Markdown or target text could become active HTML. The page treats
  both as text.
- Poll responses can arrive out of order. Older revisions do not replace a
  newer render.
- A transient outage can make current state look frozen. The last good render
  is retained but visibly marked stale.
- Reusing the milestone panel could turn discussion into milestone chronology.
  The view remains a separate page and projection.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Dedicated routes and envelope | `GET /brainstorming.html?session=<session_id>` serves the Brainstorming-only page. Its only new data route is `GET /api/brainstorming/sessions/<session_id>/view`, returning HTTP 200 and exactly `{"ok": true, "view": view}`. The page calls the existing bodyless `POST /api/brainstorming/sessions/<session_id>/stop`; Slice 6's create, detail, and stop schemas remain unchanged. View errors retain `{"ok": false, "error": code}` and the existing `forbidden`, `unknown_brainstorming_session`, and `brainstorming_unavailable` status/code mappings. | `implementation/milestones/brainstorming/skeleton.md:33-34,79,98,108`; `implementation/milestones/brainstorming/goal.md:318-334`; `implementation/milestones/brainstorming/slices/slice-06.md:125,130-132`; `orchestrator/service.py:2734-2926,3064-3085` | touch one static page route and one additive authorized view route; do-not-change the three Slice 6 routes or add a collection/event route |
| Exact view projection | `view` has exactly `id`, `caller`, `status`, `question`, `process`, `revision`, `target`, `participants`, `same_family_fallback`, `closure_policy`, `closure_ballots`, `round`, `transcript_markdown`, and `result`. Identity/process/revision come from the exact standalone projection. Participants retain roster order and exact resolved assignments. `closure_ballots` contains every accepted ballot in transcript order. `round` is exactly `{current, completed, maximum}`: current is the latest accepted turn's round or `0`, completed is durable `rounds_used` or `0`, and maximum is request `max_rounds`. `result` is `null` before terminal state and otherwise the exact durable result. | `implementation/milestones/brainstorming/skeleton.md:25-34,79,100,103-105,108`; `implementation/milestones/brainstorming/goal.md:320-329`; `orchestrator/brainstorming.py:500-596,660-743,829-899,981-1008,1205-1291`; `orchestrator/brainstorming_lifecycle.py:772-788` | touch one deterministic display projection over validated state; do-not-add inferred opinions, milestone actions, provider-session references, or mutable UI state to durable state |
| Transcript and target | `transcript_markdown` is the canonical complete `chat.md` rendering of the same durable state revision. `target` is exactly `{ref, revision, exists, content, truncated}`. `ref` is the request target reference; before an accepted target revision the other four values are `null`, `null`, `null`, and `false`. Otherwise `revision` identifies the accepted Brainstorming revision and `exists` is exact. UTF-8 text is exposed as `content` up to the existing `ARTIFACT_MAX` text limit with `truncated` set truthfully; absent or non-UTF-8 content is `null` and never fabricated. The page inserts transcript and target content as text, not HTML. | `implementation/milestones/brainstorming/skeleton.md:25-28,33-34,79,103-105,108`; Operator Amendment A1, **Target versioning clarification**; `orchestrator/brainstorming.py:352-424,660-743,1918-2007,2030-2042`; `orchestrator/service.py:2441,2490-2525`; `orchestrator/static/panel.html:1299-1301,2030-2042` | touch canonical transcript rendering and immutable accepted-target reads; do-not-read a live unaccepted target, edit any path, execute supplied markup, or expose binary/base64 content |
| Refresh and stop behavior | The page polls the view route at the neighbouring panel cadence: 2 seconds locally and 30 seconds through the recognized ngrok hostnames. A stale request sequence or lower durable revision cannot replace a newer render. On a transient failure the last good view remains with an explicit stale warning and polling continues. Stop is enabled only for a nonterminal session and sends no fields to the existing stop route. After a successful stop response, the page immediately refreshes the view and continues polling; the stop response schema is unchanged. There is no push or delivery guarantee. | `implementation/milestones/brainstorming/skeleton.md:29-34,79,108`; `implementation/milestones/brainstorming/slices/slice-06.md:37-45,89-94,125,130,144,147-149`; `orchestrator/static/panel.html:1749-1759,2030-2042,3178-3193` | touch eventual page refresh, stale indication, and the existing stop consumer; do-not-add a new stop meaning, status, event, cursor, or transport |
| Access and process independence | The immutable Brainstorming service record is authorized before session state, transcript, or target revision is read. A denied or unknown request returns only the pinned error envelope, and the page clears any previously rendered session content rather than treating that refusal as a transient stale read. The page shell contains no session data. The view reads Brainstorming state only; it neither reads nor writes milestone ledger/registry state, and the existing milestone panel contains no embedded Brainstorming conversation or required link. | `implementation/milestones/brainstorming/skeleton.md:36-47,65-67,79,98,108`; `implementation/milestones/brainstorming/goal.md:17-26,331-334,376-386`; `orchestrator/service.py:2691-2710,2817-2833`; `orchestrator/brainstorming_lifecycle.py:748-788,932-936` | touch the existing Brainstorming authorization and independent projection seams; do-not-inspect before authorization or touch milestone state, `/api/runs`, or `panel.html` |
| Slice boundary | This slice adds only the dedicated read view and its stop control. It adds no creation/listing/search API, launch form, transcript/state mutation, target editor, diagnostic stream, milestone adapter/link, external-repository change, or repository/VCS behavior. Existing exact Brainstorming request, state, result, lifecycle, and error contracts remain the authority. | `implementation/milestones/brainstorming/skeleton.md:36-47,73-80,94-108`; `implementation/milestones/brainstorming/goal.md:300-334,376-386`; `implementation/milestones/brainstorming/slices/slice-06.md:25-28,58-71,119-132` | touch `orchestrator` visualization/service tests and the new static view only; do-not-touch external roots, milestone workflow, or earlier sealed contracts |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_visualization`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| The surface is dedicated and exact | `test_dedicated_page_and_routes_are_brainstorming_only` | The page route serves the Brainstorming shell; the view route returns only the pinned envelope/schema; missing paths are refused; existing lifecycle and milestone routes retain their exact responses. | strict |
| One authorized revision drives the view | `test_view_projection_is_authorized_exact_and_revision_coherent` | Administrative and project-bound reads authorize before state access, preserve roster/policy order, and return transcript, rounds, ballots, target, status, and result from one revision; foreign and unknown reads expose no session content and clear any prior render. | strict |
| Discussion, target, and result converge in order | `test_transcript_ballots_target_and_result_follow_accepted_state` | Successive snapshots show accepted turns and ballots in order, canonical complete Markdown, the referenced accepted target revision, and then the exact terminal result without reading an unaccepted live target. | strict state; eventual observation |
| Target preview limits are honest | `test_absent_binary_and_large_target_previews_are_honest` | Not-yet-accepted and absent targets, binary bytes, exact UTF-8 text, and oversized text produce the pinned null/content/truncation outcomes while reference and revision remain accurate. | strict |
| Polling, stale state, and stop retain inherited semantics | `test_page_poll_stop_and_stale_contract` | The page uses the pinned cadence, rejects stale responses, retains and marks the last good render after a failed read, submits the bodyless stop, and cannot turn a stop/completion race into two terminal outcomes. | eventual refresh; optimistic race; strict winner |
| Milestone chronology is untouched | `test_milestone_panel_routes_and_state_remain_unchanged` | `/api/runs`, milestone registry/state sentinels, and `panel.html` remain byte/behavior identical and contain no Brainstorming transcript projection. | strict compatibility |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:321-324`).

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for every guarantee this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **verified current consumers:** the local service's static/JSON dispatcher and immutable Brainstorming access gate; the standalone lifecycle projection; the validated session/transcript/target-revision store; and the existing panel's accepted polling and safe-text conventions. **new direct consumer:** a human following one known standalone session and the focused visualization suite. **not touched:** milestone state/routes/panel and the read-only Agent99, Life, LPC, and Tutor roots. | `orchestrator/service.py:2691-2926,3064-3085`; `orchestrator/brainstorming_lifecycle.py:748-788,932-936`; `orchestrator/brainstorming.py:1205-1291,1918-2042`; `orchestrator/static/panel.html:1570-1587,1749-1759,2030-2042,3178-3193`; `implementation/milestones/brainstorming/skeleton.md:73-80` |
| pinned_facts | **closed facts:** the dedicated page and one view route; exact view envelope/schema; canonical transcript and accepted-target projection; polling, stale, and stop behavior; pre-read access; and the no-milestone/no-new-lifecycle boundary. | `implementation/milestones/brainstorming/slices/slice-07.md:105-114`; `implementation/milestones/brainstorming/skeleton.md:23-47,79,94-108`; Operator Amendment A1, **Target versioning clarification** |
| verification | **focused:** six named checks pin the routes/schema, pre-read authorization and one-revision consistency, ordered transcript/ballot/target/result convergence, honest target previews, polling/stale/stop behavior, and milestone compatibility. **full:** repository unittest discovery remains the milestone gate. | `implementation/milestones/brainstorming/slices/slice-07.md:116-133`; `implementation/milestones/brainstorming/skeleton.md:124-137`; `orchestrator/README.md:321-324` |
| reuse_posture | **checked:** service static/JSON/access/error conventions; the exact lifecycle detail/stop surface; validated session, transcript, ballot, result, and accepted-target revisions; current panel polling, stale-response, stale-banner, and inert-text patterns; and the non-canonical machine-projection note. **adopted:** those existing mechanisms and guarantee levels. **new-with-why:** one view projection and one separate page are required because the exact lifecycle response exposes neither canonical transcript text nor accepted-target preview, while the sealed boundary requires both and forbids milestone-panel embedding. | `orchestrator/service.py:2691-2926,3064-3085`; `orchestrator/brainstorming_lifecycle.py:772-788,932-936`; `orchestrator/brainstorming.py:829-899,981-1008,1205-1291,1918-2042`; `orchestrator/static/panel.html:1570-1587,1749-1759,2030-2042,3178-3193`; `implementation/milestones/brainstorming/slices/slice-06.md:125,132`; `implementation/milestones/brainstorming/skeleton.md:79,108`; `implementation/brainstorming/machine-api-and-persona-projection.md:31-55,57-113` |
| enforceability | **snapshot/schema:** validated SessionStore revision plus exact route tests. **transcript/target:** canonical renderer plus immutable accepted revision reads and a bounded preview. **access:** immutable service binding before all reads. **safe display:** text insertion and hostile-content fixtures. **eventual refresh:** existing cadence, request-sequence/revision guard, and stale-render pattern. **stop:** existing target-safe lifecycle endpoint and single durable winner. **independence:** separate static/API routes plus milestone byte/behavior sentinels. Browser delivery, push, and perfect liveness remain explicitly unpromised. | `implementation/milestones/brainstorming/slices/slice-07.md:173-186`; `orchestrator/brainstorming.py:352-424,1205-1291,1918-2042`; `orchestrator/brainstorming_lifecycle.py:748-788,932-936,1026-1035`; `orchestrator/service.py:2691-2926`; `orchestrator/static/panel.html:1299-1301,1749-1759,2030-2042,3178-3193` |

### Reuse Posture

- **Checked:** the service's static-file, JSON-envelope, typed Brainstorming
  error, identity, and project-access seams; Slice 6's exact inspect and stop
  surface; SessionStore validation, transcript rendering, and retained target
  versions; the panel's polling, response-order, stale-banner, and safe-text
  behavior; and the non-canonical machine/Persona projection note.
- **Adopted:** the existing response framing, immutable pre-read authorization,
  one-revision session projection, canonical transcript renderer, accepted
  target-version reads, artifact preview limit, polling cadence, stale-view
  convention, and target-safe stop.
- **New-with-why:** one deterministic view projection supplies canonical
  transcript text and the accepted target preview from the same session
  revision; one separate page renders it. Slice 6's exact response cannot grow
  those fields, client-side transcript reconstruction would duplicate the
  canonical renderer, and the sealed design requires a dedicated visualization
  outside milestone chronology. Authorities:
  `implementation/milestones/brainstorming/skeleton.md:33-34,79,98,108`;
  `implementation/milestones/brainstorming/slices/slice-06.md:125,132`;
  `orchestrator/brainstorming.py:1918-2042`.
- **Compatibility:** the lifecycle routes, durable state, transcript, target
  versions, milestone panel, and `/api/runs` remain unchanged. The page is a
  replaceable consumer of the stable view projection, not a new authority.

### Enforceability Gate

| invariant asserted here | mechanism that can enforce it | implementation gate |
|---|---|---|
| Exact authorized one-revision view | Immutable service-record authorization before `SessionStore.read`, whose snapshots pass exact state validation (`orchestrator/brainstorming_lifecycle.py:748-788,932-936`; `orchestrator/brainstorming.py:1205-1291`) | Route tests reject unknown/foreign reads before content access, clear prior page content on those refusals, and compare every projected field with one captured durable revision. |
| Canonical ordered transcript and accepted target | Version-selected canonical transcript rendering and immutable target-revision lookup (`orchestrator/brainstorming.py:352-424,1918-2007,2030-2042`) | Transition matrices compare the projection with `chat.md`, accepted ballot order, and the target bytes named by the same state's accepted revision. |
| Honest bounded target preview | Existing artifact-view cap (`orchestrator/service.py:2441,2490-2525`) plus exact existence/bytes validation (`orchestrator/brainstorming.py:360-424`) | Absent, binary, UTF-8, empty, and oversized fixtures pin null/content/truncation without reading the live target path. |
| Participant content cannot execute as page markup | The accepted panel uses `textContent` for untrusted plain-text surfaces (`orchestrator/static/panel.html:1299-1301,2030-2042`); this view uses the same text-only presentation | Hostile transcript/target fixtures remain visible text and create no element, handler, navigation, or script. |
| Eventual refresh never regresses visible truth | Existing response-sequence guard, last-good stale banner, and local/remote cadence (`orchestrator/static/panel.html:1749-1759,2030-2042,3178-3193`) | Page-contract tests deliver responses out of order and inject transient errors; revision never decreases and stale state is explicit. |
| Stop has one target-safe terminal winner | Existing authorized stop route and lifecycle stop/terminalization (`orchestrator/service.py:2900-2926`; `orchestrator/brainstorming_lifecycle.py:1026-1035`; `implementation/milestones/brainstorming/slices/slice-06.md:130,147-149`) | The view sends the exact bodyless request, refreshes after its returned winner, and cannot display a second terminal result after a completion race. |
| Brainstorming stays outside milestone chronology | Independent-process boundary and separate standalone state/API/view (`implementation/milestones/brainstorming/skeleton.md:36-47,65-67,79,98,108`) | Milestone API/state/panel sentinels stay unchanged and the dedicated page contains no milestone timeline projection. |

No mechanism here promises push delivery, a perfectly current browser, or
perfect provider liveness; those remain eventual or best-effort as stated.

### Planning Material Disposition

- **Adopt:** the sealed skeleton as the operative boundary and the generated
  goal snapshot only for the minimum facts the visualization must show.
- **Revise:** the older machine-projection note's separation between durable
  truth and a consumer projection into one Brainstorming-only read view using
  the accepted local polling contract.
- **Reject:** that note's milestone event cursor, API-version field, replacement
  error object, bearer token, push transport, attention state, digest, Persona
  projection, and all milestone-ledger or external-product coupling.

Authority:
`implementation/milestones/brainstorming/skeleton.md:3-5,33-47,79,94-122`;
`implementation/brainstorming/README.md:3-8,12-17`;
`implementation/brainstorming/machine-api-and-persona-projection.md:31-55,57-113`.
