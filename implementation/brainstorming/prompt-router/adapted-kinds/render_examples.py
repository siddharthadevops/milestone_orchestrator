#!/usr/bin/env python3
"""Render the seed corpus with frozen representative values.

Milestone payloads retain captured values where they still fit the target.
Brainstorming values deliberately exercise the target one-repo/Git topology;
the retired captured work area remains only in current-prompts.md.
"""
import json
import re
import sys
from pathlib import Path

KINDS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(KINDS_DIR.parents[3]))

from orchestrator import prompt_router, prompt_sets, prompts

BASE = KINDS_DIR.parent
CAPTURES = (BASE / 'current-prompts.md').read_text().splitlines()

def cap(lo, hi=None, strip_prefix=None):
    """1-based inclusive line range from current-prompts.md, verbatim."""
    hi = hi or lo
    text = '\n'.join(CAPTURES[lo - 1:hi])
    if strip_prefix:
        assert text.startswith(strip_prefix), f'lines {lo}-{hi} missing prefix {strip_prefix!r}'
        text = text[len(strip_prefix):]
    return text

# --- frozen representative payloads ----------------------------------------
ECOSYSTEM = cap(961, 965)
AMENDMENTS_A = cap(1275, 1277)

# Catalogue snapshot FROZEN 2026-08-23 (id+description projection) so the
# golden renders are stable; the capture elided the original entry and the
# live catalogue keeps evolving.
CATALOGUE = '''[
  {
    "description": "Runs one contracted agent call for focused work.",
    "id": "agent_call"
  },
  {
    "description": "Runs a bounded discussion whose lead applies the agreed work.",
    "id": "brainstorming"
  }
]'''
ADJUDICATIONS = cap(1480, 1481)
DEBT = cap(1792, 1795)
QUEUED = cap(2318, 2331)
CONSULT_CMD = cap(2458).strip()
WS = '/Users/siddhartha/Development/source/milestone_orchestrator_impl'
GOAL = 'implementation/milestones/staffing-router/goal.md'
SKELETON = 'implementation/milestones/staffing-router/skeleton.md'
NOTE10 = 'implementation/milestones/staffing-router/slices/slice-10.md'
ROUNDS = '20'
# Stable, existing Git commits used as topology fixtures; the prompt payloads
# are representative, not claims about what those historical commits changed.
WIPE_REVISION = '3abbd13e7c966cbeeac773870dfd0eb115d596f1'
PRE_SESSION_REVISION = '109f276ebd03825a8d8f8e0947487765b6860ed1'
ACCEPTED_REVISION = '2e8896da126916cc408f2c1c402046372cd5d63d'
BS_ACCEPTED_REVISION = '0ea745bdfa27c4ca11a6bbc7e726ed78cb4b38e5'

BS_ECOSYSTEM = '''- PRIMARY ROOT /Users/siddhartha/Development/source/life_prod/ai_capability_certification — the repo you execute in.
- ADDITIONAL ROOT /Users/siddhartha/Development/source/life — a READ-ONLY grant: you may read it for evidence; never edit it.
- ADDITIONAL ROOT /Users/siddhartha/Development/source/life_prod/agent_99 — a READ-ONLY grant: you may read it for evidence; never edit it.
- ADDITIONAL ROOT /Users/siddhartha/Development/source/life_prod/life_product_components — a READ-ONLY grant: you may read it for evidence; never edit it.'''
BS_COMMON = {
    'ecosystem_map': BS_ECOSYSTEM,
    'chat_path': '/Users/siddhartha/.impl_roadmap/brainstorming/state/kv.json.sessions/1be28264ef51cac17ad7e2bf4b6b29fd75de2660ea53159f5199572494426d9d/chat.md',
    'target_path': '/Users/siddhartha/Development/source/life_prod/ai_capability_certification/implementation/milestones/m9/skeleton.md',
    'reference_documents': '  - implementation/milestones/m9/skeleton.md\n  - implementation/milestones/m9/goal.md',
    'workspace_path': '/Users/siddhartha/Development/source/life_prod/ai_capability_certification',
}

RUNS = {
    'merge_repair': {
        'route': {'job': 'merge_repair@workspace', 'executor': 'agent_call',
                  'material': 'code'},
        'values': {'kind': 'merge_repair', 'workspace': WS,
                   'ecosystem_map': ECOSYSTEM,
                   'wipe_reason': 'deleted built slices 4 and 5; slices 6-8 were unwound and requeued',
                   'wipe_boundary': WIPE_REVISION,
                   'source_kind': 'brainstorming_session',
                   'source_base_role': 'pre_session_commit',
                   'source_base_revision': PRE_SESSION_REVISION,
                   'accepted_revision': ACCEPTED_REVISION,
                   'apply_outcome': 'conflicted',
                   'apply_diagnostics': 'CONFLICT (content): implementation/milestones/staffing-router/skeleton.md has markers and an unmerged index entry; all other paths applied cleanly'},
    },
    'merge_repair.agent_call': {
        'kind_file': 'merge_repair',
        'route': {'job': 'merge_repair@workspace', 'executor': 'agent_call',
                  'material': 'code'},
        'values': {'kind': 'merge_repair', 'workspace': WS,
                   'ecosystem_map': ECOSYSTEM,
                   'wipe_reason': 'forbidden reorder first diverged at built position 4; slices 4-8 were unwound and requeued',
                   'wipe_boundary': WIPE_REVISION,
                   'source_kind': 'agent_call',
                   'source_base_role': 'pre_call_commit',
                   'source_base_revision': PRE_SESSION_REVISION,
                   'accepted_revision': ACCEPTED_REVISION,
                   'apply_outcome': 'clean',
                   'apply_diagnostics': 'none'},
    },
    'suite_checkpoint': {
        'route': {'job': 'suite_checkpoint@workspace', 'executor': 'agent_call',
                  'material': 'code'},
        'values': {'kind': 'suite_checkpoint', 'workspace': WS,
                   'ecosystem_map': ECOSYSTEM,
                   'checkpoint_reason': 'four_slice_checkpoint',
                   'verification_commands': 'python3 -m unittest discover -s orchestrator/tests -t .'},
    },
    'draft_skeleton': {
        'route': {'job': 'draft_skeleton@skeleton', 'executor': 'agent_call',
                  'material': 'document'},
        'values': {'kind': 'draft_skeleton', 'workspace': WS,
                   'goal_path': GOAL, 'skeleton_path': SKELETON,
                   'project': 'orchestrators', 'work_area': 'implementation', 'ecosystem_map': ECOSYSTEM,
                   'task_executor_catalogue': CATALOGUE},
        # capture of 2026-08-18: no amendments existed yet -> both units drop
    },
    'draft_slice_note': {
        'route': {'job': 'draft_slice_note@slice_doc', 'executor': 'agent_call',
                  'material': 'document'},
        'values': {'kind': 'draft_slice_note', 'workspace': WS,
                   'slice_id': '10', 'slice_title': 'Compatibility and conformance',
                   'skeleton_path': SKELETON, 'goal_path': GOAL, 'slice_note_path': NOTE10,
                   'operator_amendments': AMENDMENTS_A,
                   'project': 'orchestrators', 'work_area': 'implementation', 'ecosystem_map': ECOSYSTEM,
                   'brainstorming_max_rounds': ROUNDS},
        # no SLICE PRODUCER PLANNING in this capture -> producer_planning drops
    },
    'implement': {
        'route': {'job': 'implement@slice_impl', 'executor': 'agent_call',
                  'material': 'code'},
        'options': {'implementation_metering': True},
        'values': {'kind': 'implement', 'workspace': WS,
                   'slice_id': '10', 'slice_title': 'Compatibility and conformance',
                   'skeleton_path': SKELETON, 'goal_path': GOAL, 'slice_note_path': NOTE10,
                   'operator_amendments': AMENDMENTS_A,
                   'project': 'orchestrators', 'work_area': 'implementation', 'ecosystem_map': ECOSYSTEM,
                   'brainstorming_max_rounds': ROUNDS,
                   'implementation_scope': prompts._implementation_scope_block({
                       'part': 'b',
                       'scope': 'Complete the remaining compatibility proof.',
                       'delegated_remaining': None,
                       'source_unit': 'slice_impl-10-a',
                   }).rstrip('\n')},
    },
    'review_round': {
        'route': {'job': 'review_round@slice_impl', 'executor': 'agent_call',
                  'material': 'code'},
        'variants': {'target_frame': 'slice_unit'},
        'values': {'kind': 'review_round', 'workspace': WS,
                   'task': 'full review round of the slice 10 implementation (Compatibility and conformance).',
                   'skeleton_path': SKELETON, 'goal_path': GOAL,
                   'target': '(workspace) (plus any code/tests it governs)',
                   'reference_path': NOTE10,
                   'operator_amendments': AMENDMENTS_A,
                   'project': 'orchestrators', 'work_area': 'implementation', 'ecosystem_map': ECOSYSTEM,
                   'adjudicated_rejections': ADJUDICATIONS,
                   'brainstorming_max_rounds': ROUNDS},
        'options': {'scope_authority': True, 'impl_review_duty': True, 'altitude_review': False},  # impl target
        # no deferred debt on this impl unit -> unit drops
    },
    'delta_review': {
        'route': {'job': 'delta_review@slice_doc', 'executor': 'agent_call',
                  'material': 'document'},
        'variants': {'target_frame': 'slice_unit'},
        'values': {'kind': 'delta_review', 'workspace': WS,
                   'task_subject': 'the slice 10 note (Compatibility and conformance)',
                   'delta_base_revision': PRE_SESSION_REVISION,
                   'skeleton_path': SKELETON, 'goal_path': GOAL,
                   'reference_path': SKELETON,
                   'operator_amendments': AMENDMENTS_A,
                   'project': 'orchestrators', 'work_area': 'implementation', 'ecosystem_map': ECOSYSTEM,
                   'deferred_debt': DEBT, 'adjudicated_rejections': ADJUDICATIONS,
                   'brainstorming_max_rounds': ROUNDS},
        'options': {'scope_authority': False, 'doc_review_duty': True, 'altitude_review': True},  # doc target
    },
    'reclassify': {
        'route': {'job': 'reclassify@doc', 'executor': 'agent_call',
                  'material': 'document'},
        'values': {'kind': 'reclassify', 'workspace': WS,
                   'project': 'orchestrators', 'work_area': 'implementation', 'ecosystem_map': ECOSYSTEM,
                   'artifact_path': NOTE10,
                   'builders': 'slice docs drafted by codex (gpt-5.6-sol, max effort); implementation built by codex (gpt-5.6-sol, max effort)',
                   'finding_severity': 'P2', 'finding_id': 'S10-CLAUDE-001',
                   'finding_summary': cap(2075),
                   'finding_plain': cap(2076, strip_prefix='In plain words: '),
                   'finding_example': cap(2077, strip_prefix='Smallest failure scenario: ')},
    },
    'fix_findings': {
        'route': {'job': 'fix_findings@slice_doc', 'executor': 'agent_call',
                  'material': 'document'},
        'variants': {'target_frame': 'slice_unit'},
        'values': {'kind': 'fix_findings', 'workspace': WS,
                   'task_subject': 'the slice 10 note (Compatibility and conformance)',
                   'editable_path': NOTE10,
                   'skeleton_path': SKELETON, 'goal_path': GOAL,
                   'operator_amendments': AMENDMENTS_A,
                   'project': 'orchestrators', 'work_area': 'implementation', 'ecosystem_map': ECOSYSTEM,
                   'queued_findings': QUEUED,
                   'deferred_debt': DEBT, 'adjudicated_rejections': ADJUDICATIONS,
                   'consultation_family': 'claude', 'consultation_command': CONSULT_CMD,
                   'scratch_path': '/Users/siddhartha/Development/source/milestone_orchestrator_impl/.consultations/',
                   'brainstorming_max_rounds': ROUNDS},
        'options': {'altitude_fix': True},  # doc target
    },
    'discussion_turn': {
        'route': {'job': 'rethink', 'executor': 'brainstorming',
                  'material': 'document', 'role': 'initial_position',
                  'lead': True, 'artifact_type': 'document'},
        'options': {'two_register': True, 'altitude_doc': True, 'reuse_gate': True},
        'values': {**BS_COMMON, 'kind': 'discussion_turn', 'workspace': BS_COMMON['workspace_path'], 'participant_id': 'initial-position', 'role': 'initial_position', 'round': '3',
                   'target_authority': f'Git commit {BS_ACCEPTED_REVISION}',
                   'target_state': 'present'},
        'variants': {'role_stance': 'initial_position'},
    },
    'discussion_turn.contrary': {
        'kind_file': 'discussion_turn',
        'route': {'job': 'rethink', 'executor': 'brainstorming',
                  'material': 'document', 'role': 'contrary_position',
                  'lead': False, 'artifact_type': 'document'},
        'options': {'evidence': True, 'altitude_review': True},
        'values': {**BS_COMMON, 'kind': 'discussion_turn', 'workspace': BS_COMMON['workspace_path'], 'participant_id': 'contrary-position', 'role': 'contrary_position', 'round': '3',
                   'target_authority': f'Git commit {BS_ACCEPTED_REVISION}',
                   'target_state': 'present'},
        'variants': {'role_stance': 'contrary_position'},
    },
    'questioner_turn': {'options': {'reuse_gate_questioner': True, 'altitude_questioner': True},
        'route': {'job': 'rethink', 'executor': 'brainstorming',
                  'material': 'document', 'role': 'common_sense',
                  'lead': False, 'artifact_type': 'document'},
        'values': {**BS_COMMON, 'kind': 'questioner_turn', 'workspace': BS_COMMON['workspace_path']}},
}

# --- renderer ---------------------------------------------------------------
def kind_path(kind):
    for sub in ('milestone', 'brainstorming'):
        p = KINDS_DIR / sub / f'{kind}.json'
        if p.exists():
            return p
    raise FileNotFoundError(kind)

PLACEHOLDER = re.compile(r'\{\{(\w+)\}\}')
PROMPT_SET = prompt_sets.default_seed()

def render_unit(unit, values):
    """Render one unit; return text or None (unit dropped)."""
    text = '\n'.join(unit['text'])
    declared = {v['name']: v for v in unit.get('variables', [])}
    for name in set(PLACEHOLDER.findall(text)):
        if name in values:
            text = text.replace('{{%s}}' % name, str(values[name]))
        elif 'default' in declared.get(name, {}):
            text = text.replace('{{%s}}' % name, str(declared[name]['default']))
        elif declared.get(name, {}).get('drop_unit_if_absent'):
            return None
        else:
            raise KeyError(f"missing required variable '{name}'")
    return text

def render_kind(kind, spec):
    values = spec.get('values', {})
    prompt = prompt_router.assemble(
        PROMPT_SET, values=values, **spec['route']
    )
    blocks = [render_unit(unit, values) for unit in prompt['instructions']]
    questions = prompt['questions']
    if questions['items']:
        lines = list(questions['intro'])
        lines.extend(f"- {item['id']}: {item['text']}" for item in questions['items'])
        blocks.append('\n'.join(lines))
    blocks.extend(render_unit(unit, values) for unit in prompt['output_contract'])
    return '\n\n'.join(blocks) + '\n'

def render_all(output_dir=KINDS_DIR):
    """Render every declared run and return its relative output inventory."""
    output_dir = Path(output_dir)
    emitted = []
    for output_name, spec in RUNS.items():
        kind = spec.get('kind_file', output_name)
        relative = kind_path(kind).relative_to(KINDS_DIR).with_name(
            f'{output_name}.prompt.txt'
        )
        out = output_dir / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        rendered = render_kind(kind, spec)
        out.write_text(rendered)
        emitted.append((relative.as_posix(), len(rendered.splitlines())))
    return tuple(emitted)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        destination = KINDS_DIR
    elif len(sys.argv) == 3 and sys.argv[1] == '--output-dir':
        destination = Path(sys.argv[2])
    else:
        raise SystemExit('usage: render_examples.py [--output-dir PATH]')
    for relative, line_count in render_all(destination):
        print(f'{relative}: {line_count} lines')
    print('OK')
