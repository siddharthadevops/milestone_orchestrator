# Slice 06 — Deep documentation and child authority

## Register 1 — INTENT (lay language)

### What this slice builds

This slice makes `deep_task` orderable through the same task catalogue, API,
and generated form as every other public task. One deep order represents one
coherent slice-sized request. Its first delivered work is exactly one public
`reviewed_task` for the slice note. That child performs the complete reviewed
documentation cycle and owns its own evidence, accounting, seal, result, and
gate commit.

The parent and child remain separate durable tasks. The child records which
deep task ordered it, that it is the documentation phase, and that no
implementation part applies. This relationship—not a chip, thread, or inferred
ordering—is what restart uses. A crash before admission may try again; a crash
after admission must find and reuse the same child.

The deep order stores separate documentation and implementation choices before
work starts. This slice consumes only the documentation choices. It freezes the
implementation choices so Slice 7 can use the same admitted authority rather
than reading newer defaults. It does not yet admit implementation work or
declare the deep task successful.

### Ownership and consumers

The deep parent owns only composition: the frozen child policies, documentation-
first boundary, and durable child identity. The documentation child remains an
ordinary `reviewed_task`; parentage grants no different review behavior or
private entry point. The shared task service and store retain admission,
visibility, access, and persistence ownership. Prompt Router, Staffing Router,
the reviewed lifecycle, and Git retain their existing authority.

The immediate consumers are the generic service, standalone host/store, and
catalogue-generated panel. Milestone composition and product integrations remain
later callers of the same public records; no granted product root is changed.

### Guarantee posture

- **Strict:** a valid deep order durably resolves both child policies before
  effects; exactly one documentation child is admitted for one parent/phase;
  the child is the public `reviewed_task` contract; its relationship, terminal
  result, seal, gate commit, and accounting remain authoritative; restart
  reuses that child; implementation cannot appear before it and is not admitted
  by this slice; old records retain their original meaning.
- **Best-effort:** physical-call uniqueness and provider delivery retain the
  reviewed lifecycle's at-least-once limit. Child grouping, chips, navigation,
  and display freshness remain conveniences and cannot control execution.
- **Optimistic / eventual:** none. This slice adds no queue, redelivery,
  replication, eventual-display, or exactly-once promise.

### Dependencies

This slice depends on Slices 1–5: the reusable reviewed lifecycle and policy,
direct routed-call evidence, gate-backed native result, and public standalone
`reviewed_task`. It reuses the common request/order/result contracts, effective
project defaults, project and path checks, Git-root and work-area guards,
canonical task records, standalone store lock and compare-and-set write, open-
task adoption, and catalogue-driven form.

It adds no third-party dependency, service process, scheduler, queue, event bus,
relationship store, accounting ledger, prompt path, staffing authority, or
product adapter.

### Non-goals

- No implementation child, implementation part, size-cut continuation, deep
  terminal result, parent accounting aggregate, or aggregate commit. Slice 7
  owns those outcomes; this slice is not a release boundary by itself.
- No bare documentation or implementation leg and no private child API.
- No milestone skeleton/slice composition, canonical-plan establishment,
  design repair, verification cadence, closure, deployment, or run accounting.
- No size monitoring or intervention by `deep_task`. The documentation child
  cannot activate size control; the frozen implementation policy does not run.
- No new route, public result status, event vocabulary, retry endpoint,
  permission model, migration, history backfill, or special panel grouping.
- No defensive parser for parent/phase/part values emitted by this product;
  tests prove their outcome and uniqueness instead of corrupting trusted
  records to test imaginary input.

### Acceptance criteria

The shared catalogue must expose `deep_task` as the fourth public executor and
the generated panel must render its two independent policy groups without a
deep-specific form or route. A valid order must resolve both policies from the
bound work area's effective defaults before acknowledging one parent record.
Invalid policy, access, path, Git-root, Git-disabled, or busy-work-area requests
must refuse before a parent, child, provider call, or edit exists.

The parent must admit exactly one documentation child whose stored order is an
ordinary `reviewed_task` with semantic job `draft_slice_note`, the parent's
request and staffing session, and the parent's frozen documentation policy. The
child must be readable through the generic task API and carry the canonical
relationship. It must reach its own reviewed result and gate commit without an
internal `agent_call` task. At that boundary the parent remains open, no
implementation child exists, and no parent commit or accounting result is
fabricated.

Focused tests must inject failures immediately before and after related-child
admission and race recovery attempts. Every case must converge on zero or one
admission followed by reuse of one exact child id; no second provider lifecycle
may begin. A terminal child needed by an open parent cannot be deleted. Existing
direct tasks, reviewed-task behavior, old records, task routes, and best-effort
presentation must remain unchanged.

### Risks

The main risks are acknowledging unresolved child policy, admitting a private or
weakened documentation task, losing the relationship in a crash window,
duplicating calls after restart, re-resolving changed project defaults, allowing
deletion of live recovery authority, or admitting implementation too early.
Other risks are treating display grouping as authority, activating size control
at the parent or documentation phase, adding a second store, changing old task
records, or reporting deep success from documentation alone. The admission,
relationship, crash-race, deletion, child-result, and compatibility checks below
make those faults observable.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Public executor and routes | The ordered public ids become exactly `agent_call`, `brainstorming`, `reviewed_task`, `deep_task`. `deep_task` uses only the mandated generic catalogue/order/read surfaces: `GET /api/task-executors`, `GET/POST /api/tasks`, and `GET /api/tasks/<id>`. | slice assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:114`; public contract `implementation/milestones/deep-reviewed-tasks/skeleton.md:128`; current routes `orchestrator/service.py:4627-4679,4879-4886` | touch the shared catalogue, order resolver, host, and generic projections; do-not-add `/api/deep-tasks`, a private caller path, or a panel-only order shape |
| Deep configuration | `configuration` has exactly optional objects `documentation` and `implementation`; admission stores both fully resolved. Each reuses the public reviewed-policy keys without `task_kind`: `producer`, `review_breadth`, `same_family_second_look`, its applicable `doc_reclassify_from` or `impl_reclassify_from`, `p3_reclassify_debt`, `p3_defer_max_risk`, `max_rounds_per_family`, `max_fix_loops`, `delta_full_review_after_fixes`, and implementation-only applicable `implementation_size_control`. Their semantic jobs are fixed to `draft_slice_note` and `implement`. Omission independently inherits the effective work-area defaults. | independent child choices `implementation/milestones/deep-reviewed-tasks/skeleton.md:60-68,135`; existing exact policy and defaults `orchestrator/tasks.py:627-798`; semantic names `orchestrator/contracts.py:52-55` | touch one deep resolver/schema over the existing reviewed-policy resolver; do-not-copy policy validation, expose `task_kind` inside either group, resolve implementation later, or mutate project defaults |
| Admission and errors | The common request, staffing session, access, readable-root/output containment, required Git gating, primary repo-root, and work-area exclusion remain the reviewed-task contract. Unknown nested producers return `unknown_task_executor`; malformed or inapplicable deep policy returns `invalid_task_request`; a non-own-root primary returns `primary_not_repo_root`; overlap returns `work_area_busy`, all before records or effects. | order/request validation `orchestrator/tasks.py:392-435,897-928`; reviewed project/root resolution `orchestrator/service.py:4111-4136,4193-4258`; exclusion `orchestrator/service.py:4326-4352` | touch deep configuration resolution and preflight only; do-not-weaken shared access/path/Git rules, acknowledge a half-resolved parent, or invent a composite error vocabulary |
| Documentation child and relationship | The first and only child admitted here has `order.task_executor: "reviewed_task"`, `order.configuration.task_kind: "draft_slice_note"`, the parent's exact admitted request and staffing session, and its frozen documentation policy. Its canonical record adds exactly `parent: {"task_id": <deep id>, "phase": "documentation", "part": null}`; the child record's own top-level `id` is the admitted child identity. Public orders cannot supply `parent`. | composition `implementation/milestones/deep-reviewed-tasks/skeleton.md:60-68,114,135-136`; public reviewed order `orchestrator/tasks.py:763-809,897-928`; canonical record `orchestrator/tasks.py:1047-1068` | touch the canonical record/admission contract and deep composition; do-not-embed the child, add a relationship store, infer parentage from time/order, accept caller-authored parentage, or create a child-only reviewed variant |
| Documentation-first boundary | No implementation child may be admitted before the documentation child succeeds, and this slice admits none afterward. The documentation child owns and preserves its native result, accounting, seal, and gate commit. The deep parent remains `result: null`; documentation success alone creates no parent result, accounting, commit, or success claim. | slice boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:114-115`; composition and commit law `implementation/milestones/deep-reviewed-tasks/skeleton.md:60-68,135`; reviewed result boundary `orchestrator/tasks.py:1267-1341` | touch only documentation-first composition; do-not-start Slice 7 implementation delivery, flatten the child result, copy its charges into a parent result, or add an aggregate commit |
| Uniqueness, recovery, and retention | For `(parent.task_id, parent.phase, parent.part)`, related admission is serialized and can create at most one child. Recovery after the child record exists observes or resumes that exact id, including when it is terminal; it never reorders the phase. A terminal child cannot be reopened or deleted while its parent is open. Logical identity is strict; an unrecorded physical call may repeat under the existing at-least-once law. | strict authority `implementation/milestones/deep-reviewed-tasks/skeleton.md:61-68,80-89,136`; terminal mutation `orchestrator/tasks.py:1071-1086`; store lock/CAS `orchestrator/task_api.py:132-194`; current delete seam `orchestrator/service.py:4290-4323`; delivery limit `orchestrator/state.py:1-17` | touch one serialized related-admission seam, parent recovery, and delete refusal; do-not-add a retry ledger, infer a replacement, reopen terminal records, or promise physical exactly-once delivery |
| Size and ownership boundary | `deep_task` owns no size control. The documentation child cannot expose it. The implementation group may freeze it only for an `agent_call` implementation producer, but this slice never activates it. Direct `agent_call`, direct Brainstorming, and Brainstorming-produced reviewed work remain unchanged. | operator amendment `implementation/milestones/deep-reviewed-tasks/skeleton.md:41-46,132`; existing applicability enforcement `orchestrator/tasks.py:627-726` | touch deep policy validation only; do-not-monitor the parent/documentation, move control into an executor, add Brainstorming size machinery, or consume an implementation cut |
| Compatibility and projections | Existing records are neither rewritten nor backfilled; only composite children carry `parent`. The canonical task read exposes that relationship strictly. Child grouping, links, chips, and display freshness remain best-effort and never gate admission, recovery, acceptance, or accounting. | compatibility `implementation/milestones/deep-reviewed-tasks/skeleton.md:85-89,91-104,139`; canonical reads `orchestrator/service.py:4412-4422,4507-4528`; generic panel `orchestrator/static/panel.html:5245-5384` | touch additive record projection only as required; do-not-reinterpret old tasks, require UI state for recovery, or build Slice 12 presentation early |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_deep_task_documentation orchestrator.tests.test_reviewed_task_api orchestrator.tests.test_reviewed_result orchestrator.tests.test_reviewed_policy orchestrator.tests.test_tasks orchestrator.tests.test_task_api orchestrator.tests.test_task_panel`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Catalogue, API, and panel publish one deep contract | new `DeepTaskDocumentationTest.test_catalogue_api_and_panel_publish_independent_deep_policies`; retained `TaskPanelTests.test_one_catalogue_drives_description_and_configuration` | The catalogue has exactly four ordered ids; its deep schema exposes the two exact policy groups; the generic renderer submits one generic order without deep constants, routes, or local defaults. | strict contract / best-effort display freshness |
| Invalid deep orders have no effects | new `DeepTaskDocumentationTest.test_invalid_policy_access_paths_git_and_busy_tree_refuse_before_admission` | Every named refusal returns its existing code with no parent, child, provider call, or workspace edit. Both policy groups are resolved before the parent is acknowledged. | strict |
| One public documentation child is admitted first | new `DeepTaskDocumentationTest.test_one_public_documentation_child_inherits_exact_parent_authority` | Generic task reads show one deep parent and one reviewed child with the exact order and `parent` relationship above; no private route, embedded record, internal agent-call task, or implementation child exists. | strict |
| The child owns reviewed completion | new `DeepTaskDocumentationTest.test_documentation_child_reaches_its_own_gate_while_parent_stays_open`; retained `ReviewedTaskOrderingTest.test_every_agent_call_job_reaches_reviewed_result` | The child succeeds only with its own current-byte evidence and gate commit. Its result/accounting stay on the child; the parent is open and has no native result, accounting aggregate, or commit. | strict logical result / best-effort physical-call uniqueness |
| Crash and concurrent recovery cannot duplicate the phase | new `DeepTaskDocumentationTest.test_related_admission_crash_windows_and_races_reuse_one_child` | Failure before the child write leaves none and permits one later admission; failure after it leaves one authoritative id. Concurrent recovery attempts observe that id, start at most one logical reviewed lifecycle, and never admit a second relationship. | strict logical admission and recovery / best-effort physical-call uniqueness |
| Open-parent authority cannot be erased | new `DeepTaskDocumentationTest.test_terminal_documentation_child_cannot_be_deleted_while_parent_is_open` | Generic delete refuses without changing either record or child evidence; restart still finds the same terminal child. | strict |
| Compatibility and scope remain bounded | new `DeepTaskDocumentationTest.test_slice_six_never_admits_implementation_or_completes_parent`; retained direct/reviewed task and old-record tests | No implementation record, size event, parent terminal result, aggregate charge, aggregate commit, route change, old-record rewrite, or changed direct-task behavior appears. | strict compatibility / best-effort convenience projections |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They remain the checkpoint and architectural complement and must not be claimed
as run unless implementation actually executes them
(`orchestrator/README.md:565-586`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Operators and calling products still cannot order one documentation-first slice outcome: the catalogue ends at `reviewed_task`, and the host has no composite branch. Without this slice they must manually place and remember a child, so a restart can duplicate reviewed documentation, spend calls twice, lose the child commit boundary, or begin implementation against an unreviewed note. Repository changes and records are reversible before publication; spent calls and consumed wrong-order work are not. | assigned need `implementation/milestones/deep-reviewed-tasks/skeleton.md:18-26,60-68,114`; current catalogue `orchestrator/tasks.py:105-274`; current host split `orchestrator/task_api.py:711-724` |
| machinery | This slice introduces no new runtime module or API. It extends the existing catalogue/resolver with one `deep_task` schema, the canonical task record with one trusted parent relation, the existing store with related-child admission/lookup, and the existing host with documentation-first composition and recovery. Each addition serves a required observable outcome: public ordering, independent frozen policy, public child identity, and duplicate-free restart. Focused tests are the only new test machinery. | authorised outcomes `implementation/milestones/deep-reviewed-tasks/skeleton.md:60-68,93-104,114,136`; existing catalogue/record `orchestrator/tasks.py:105-274,1047-1086`; store/host `orchestrator/task_api.py:59-194,629-724` |
| consumers_touched | Verified runtime consumers touched are the shared catalogue/order validator, direct service resolver and generic task routes, canonical standalone task store, direct host/adoption loop, generic task reads, and catalogue-generated form. The public `reviewed_task` is the created child and the reviewed lifecycle is reused unchanged. Searches across Life, Agent99, life_product_components, and Tutor found no current code consumer of either public composite id, so no product adapter is created and all granted roots remain read-only. | service admission/routes `orchestrator/service.py:4193-4258,4326-4352,4627-4679,4879-4894`; store/host `orchestrator/task_api.py:59-194,629-724`; panel `orchestrator/static/panel.html:5679-5949`; reviewed child seam `orchestrator/task_api.py:472-548,756-837` |
| cheaper_alternative | Reusing one public `reviewed_task` child and adding its relation to the canonical task record is cheapest. Documentation/configuration alone cannot prevent duplicate admission after a crash. A private reviewed entry point, embedded child, synthetic milestone, relationship store, queue, or second lifecycle duplicates existing contracts or imports unrelated law. Doing nothing leaves the mandated public composite absent. | reusable public child `orchestrator/tasks.py:144-273,763-809`; canonical store and CAS `orchestrator/task_api.py:59-194`; no-duplicate boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:91-104,135-136` |
| cost | Build cost is one nested schema/resolver, one additive record relation, one related-admission/recovery path, and focused crash/API tests. Review cost is moderate because admission crosses process-loss windows. There is no migration, dependency, daemon, extra provider, or extra store. Normal operation pays the already-selected reviewed documentation calls and Git work. Maintenance adds one composite seam; omission costs public ordering and invites manual duplicate work. Code is Git-reversible, while calls and externally consumed task outcomes are not. | standard-library environment `orchestrator/README.md:3-9,33-46`; existing task persistence `orchestrator/task_api.py:59-194`; compatibility/exclusions `implementation/milestones/deep-reviewed-tasks/skeleton.md:91-104,139` |
| threat_model | Untrusted inputs handled here are the authenticated caller's deep configuration and common request, project/work-area and path selections, and the reviewed child's provider JSON and workspace edits. Existing closed order/policy validation, access and path containment, Git-root/work-area checks, routed reply contracts, and edit detection guard them. The generated child order and `parent` relation, stored policies, task records, router answers, and child result are trusted product emissions. No validator or malformed-record test polices those trusted values; the new invariant only makes their admission unique and durable. | untrusted order boundary `orchestrator/tasks.py:392-435,627-798,897-928`; service boundary `orchestrator/service.py:4193-4258,4326-4352`; worker/edit boundary `orchestrator/runners.py:2922-2982`; `orchestrator/README.md:551-554`; trust boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:99-104` |
| pinned_facts | The eight hard rows pin only public or cross-slice deviations that are bugs: executor/routes, two policy groups, admission/errors, child order/relation, documentation-first scope, uniqueness/recovery/retention, size ownership, and compatibility/projection posture. Internal class names, storage layout, polling, control flow, and UI layout remain choices. | slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:114-115`; milestone hard contracts `implementation/milestones/deep-reviewed-tasks/skeleton.md:128,132,135-139`; existing public names `orchestrator/tasks.py:18-35,105-274` |
| verification | Seven executable rows combine a new deep-documentation contract module with retained catalogue/panel, reviewed-policy, reviewed-result, generic record/store, API, recovery, and compatibility checks. The focused command pins this slice. Repository suites remain separate gates and are not claimed without execution. | current public reviewed proof `orchestrator/tests/test_reviewed_task_api.py:297-445`; record/CAS proof `orchestrator/tests/test_tasks.py:637-816`; panel proof `orchestrator/tests/test_task_panel.py:18-61`; suite authority `orchestrator/README.md:565-586` |
| enforceability | Closed order and reviewed-policy resolvers, service access/path/Git/lease checks, immutable task results, the store's registry lock plus point CAS, generic task reads, reviewed-task host/recovery, and current child result can enforce most claims. Three mechanisms do not yet exist and are implementation gates: the deep schema/resolver, canonical `parent` relation with serialized uniqueness/retention, and a deep host/adoption path that admits or reuses the documentation child while withholding implementation and parent success. The existing store cannot currently express semantic child uniqueness, and the host treats every non-direct/non-Brainstorming executor as reviewed work; those are gaps, not present guarantees. UI grouping and physical-call uniqueness have no strict mechanism and remain best-effort. | existing enforcement `orchestrator/tasks.py:627-798,897-928,1047-1086`; `orchestrator/service.py:4193-4258,4326-4352`; `orchestrator/task_api.py:132-194,629-724,756-837`; missing catalogue id `orchestrator/tasks.py:105-274`; delivery limit `orchestrator/state.py:1-17` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Both child policies are frozen before effects | Existing reviewed-policy resolution at `orchestrator/tasks.py:627-798`; project-effective configuration and preflight at `orchestrator/service.py:4111-4258`; order persistence at `orchestrator/task_api.py:132-156`. | **Current gap:** no deep schema/resolver exists. Acceptance requires both fixed-job policies to be fully resolved on the acknowledged parent and every invalid pair to refuse before admission. |
| One phase/part has one durable child id | Registry serialization and point CAS at `orchestrator/task_api.py:132-156`; immutable top-level id and null-to-terminal result at `orchestrator/tasks.py:1047-1086`. | **Current gap:** canonical records have no `parent`, and admission has no semantic uniqueness lookup. Acceptance requires the exact relation above to be committed with the child so before/after-write crashes and concurrent recovery converge on one id without a new store. |
| The child is exactly the public reviewed-task contract | Public reviewed configuration/order at `orchestrator/tasks.py:144-273,763-809`; reviewed lifecycle/result host at `orchestrator/task_api.py:472-548,756-837`; generic task read at `orchestrator/service.py:4507-4528`. | Acceptance requires the related record to pass the same public admission and reach the same gate-backed result; no private adapter, embedded result, or internal agent-call task may satisfy the check. |
| Recovery preserves documentation-first scope | Open-task adoption at `orchestrator/task_api.py:656-703`; canonical child result at `orchestrator/tasks.py:1267-1341`; work-area ownership at `orchestrator/task_api.py:705-709`; current terminal-task deletion at `orchestrator/service.py:4290-4323`. | **Current gaps:** adoption has no `deep_task` behavior, and deletion has no parent-authority guard. Acceptance requires restart to observe/resume the recorded documentation child, protect it from deletion while the parent is open, admit no implementation child, and leave the parent non-terminal at this slice boundary. |
| No stronger delivery or display promise leaks in | At-least-once persistence limit at `orchestrator/state.py:1-17`; generic record projection at `orchestrator/service.py:4412-4422,4507-4528`; panel polling/rendering at `orchestrator/static/panel.html:5295-5384,5433-5463`. | Retain best-effort posture for calls and presentation. Strict tests inspect canonical records and logical admission, never chip freshness or physical exactly-once behavior. |
