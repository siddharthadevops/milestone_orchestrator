"""The skeleton's canonical slice-plan boundary.

This module is deliberately not a Markdown parser.  It recognizes the one
reviewed heading/fence form, validates the closed JSON contract, projects it
through the existing TaskExecutor catalogue, and anchors accepted bytes to Git.
Live callers adopt the boundary in later slices.
"""

from __future__ import annotations

import copy
import json
import os

from orchestrator import gitops, tasks
from orchestrator import state as st


HEADING = b"## Canonical slice plan"
OPEN_FENCE = b"```json"
CLOSE_FENCE = b"```"
ANCHOR_KEY = "canonical_plan_anchor"
RECONCILIATION_KEY = "accepted_range_reconciliation"
_PRODUCERS = ("draft_slice_note", "implement")


class CanonicalPlanError(ValueError):
    """The canonical block, its anchor, or its closed schema is invalid."""


class CanonicalPlanDrift(CanonicalPlanError):
    """The worktree plan differs from its last accepted Git anchor."""


class _DuplicateKey(ValueError):
    pass


def _line_body(line):
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith((b"\n", b"\r")):
        return line[:-1]
    return line


def _fence(line):
    """Return a narrow Markdown fence marker, or ``None`` for other lines."""
    body = _line_body(line)
    indent = len(body) - len(body.lstrip(b" "))
    if indent > 3:
        return None
    body = body[indent:]
    if not body or body[:1] not in (b"`", b"~"):
        return None
    marker = body[:1]
    length = len(body) - len(body.lstrip(marker))
    if length < 3:
        return None
    return marker, length, body[length:]


def _document_headings(lines):
    headings = []
    open_fence = None
    for index, line in enumerate(lines):
        fence = _fence(line)
        if open_fence is None:
            if _line_body(line) == HEADING:
                headings.append(index)
            if fence is not None:
                marker, length, rest = fence
                if marker != b"`" or marker not in rest:
                    open_fence = marker, length
        elif fence is not None:
            marker, length, rest = fence
            if (
                marker == open_fence[0]
                and length >= open_fence[1]
                and not rest.strip()
            ):
                open_fence = None
    return headings


def _document_bytes(document):
    if isinstance(document, bytes):
        return document
    if isinstance(document, str):
        try:
            return document.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CanonicalPlanError(
                "canonical-plan document must be UTF-8 text"
            ) from exc
    raise CanonicalPlanError("canonical-plan document must be bytes or text")


def _extract(document):
    document = _document_bytes(document)
    lines = document.splitlines(keepends=True)
    headings = _document_headings(lines)
    if len(headings) != 1:
        raise CanonicalPlanError(
            "canonical-plan document must contain exactly one heading"
        )
    heading = headings[0]
    if (
        heading + 1 >= len(lines)
        or _line_body(lines[heading + 1]) != OPEN_FENCE
    ):
        raise CanonicalPlanError(
            "canonical-plan heading must be immediately followed by ```json"
        )
    close = next(
        (
            index for index in range(heading + 2, len(lines))
            if _line_body(lines[index]) == CLOSE_FENCE
        ),
        None,
    )
    if close is None:
        raise CanonicalPlanError("canonical-plan JSON fence is not closed")
    return (
        b"".join(lines[heading:close + 1]),
        b"".join(lines[heading + 2:close]),
    )


def canonical_block_bytes(document):
    """Return the exact authoritative heading, fence, and payload bytes."""
    block, _payload = _extract(document)
    return block


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey("duplicate JSON key %r" % key)
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError("invalid JSON constant %s" % value)


def _decode(payload):
    try:
        text = payload.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CanonicalPlanError("canonical-plan payload is not strict JSON") from exc


def _exact_keys(value, required, optional, context):
    if not isinstance(value, dict):
        raise CanonicalPlanError("%s must be an object" % context)
    allowed = set(required) | set(optional)
    missing = sorted(set(required) - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise CanonicalPlanError("%s is missing %s" % (context, missing))
    if extra:
        raise CanonicalPlanError(
            "%s has unsupported fields %s" % (context, extra)
        )


def _text(value, context):
    if not isinstance(value, str) or not value.strip():
        raise CanonicalPlanError("%s must be a non-empty string" % context)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalPlanError("%s must be UTF-8 text" % context) from exc
    return value


def _shape(payload):
    root = _decode(payload)
    _exact_keys(root, ("slices",), (), "canonical plan")
    slices = root["slices"]
    if not isinstance(slices, list):
        raise CanonicalPlanError("canonical plan.slices must be an array")
    seen = set()
    for index, slice_plan in enumerate(slices):
        context = "canonical plan.slices[%d]" % index
        _exact_keys(
            slice_plan,
            ("id", "title", "intent", "producer_task_executor"),
            ("material",),
            context,
        )
        slice_id = slice_plan["id"]
        if type(slice_id) is not int:
            raise CanonicalPlanError("%s.id must be an integer" % context)
        if slice_id in seen:
            raise CanonicalPlanError("duplicate canonical slice id %d" % slice_id)
        seen.add(slice_id)
        _text(slice_plan["title"], "%s.title" % context)
        _text(slice_plan["intent"], "%s.intent" % context)
        if "material" in slice_plan:
            _text(slice_plan["material"], "%s.material" % context)
        producers = slice_plan["producer_task_executor"]
        _exact_keys(producers, _PRODUCERS, (), "%s producers" % context)
        for producer in _PRODUCERS:
            _text(producers[producer], "%s.%s" % (context, producer))
    return slices


def _project(slices, anchored_slices):
    catalogue = {entry["id"] for entry in tasks.task_executor_catalogue()}
    previous = {
        slice_plan["id"]: slice_plan["producer_task_executor"]
        for slice_plan in anchored_slices or []
    }
    projected = []
    for slice_plan in slices:
        retained = previous.get(slice_plan["id"])
        producers = {}
        for producer in _PRODUCERS:
            spelling = slice_plan["producer_task_executor"][producer]
            if retained is not None and retained[producer] == spelling:
                current = tasks.stored_task_executor(spelling)
            else:
                current = spelling
            if current not in catalogue:
                raise CanonicalPlanError(
                    "canonical slice %d %s has unknown TaskExecutor %r"
                    % (slice_plan["id"], producer, spelling)
                )
            producers[producer] = {"task_executor": current}
        item = {
            "id": slice_plan["id"],
            "title": slice_plan["title"],
            "intent": slice_plan["intent"],
            "producer_task_executor": producers,
        }
        if "material" in slice_plan:
            item["material"] = slice_plan["material"]
        projected.append(item)
    return projected


def validate_canonical_plan(document, anchored_document=None):
    """Validate one block and return its raw slices and state projection.

    A retired executor spelling is readable only when it is byte-for-byte the
    spelling for the same slice id and producer in the anchored prior block.
    """
    block, payload = _extract(document)
    slices = _shape(payload)
    anchored_slices = None
    if anchored_document is not None:
        _anchored_block, anchored_payload = _extract(anchored_document)
        anchored_slices = _shape(anchored_payload)
    return {
        "block": block,
        "slices": copy.deepcopy(slices),
        "projection": _project(slices, anchored_slices),
    }


def _relative_path(path):
    if not isinstance(path, str) or not path.strip():
        raise CanonicalPlanError("canonical-plan path must be non-empty")
    normalized = os.path.normpath(path)
    if os.path.isabs(normalized) or normalized == ".." or normalized.startswith(
        ".." + os.sep
    ):
        raise CanonicalPlanError("canonical-plan path must stay in the workspace")
    return normalized.replace(os.sep, "/")


def _anchor(state):
    milestone = state.get("milestone")
    if not isinstance(milestone, dict):
        raise CanonicalPlanError("run state has no milestone projection")
    anchor = milestone.get(ANCHOR_KEY)
    if anchor is None:
        return None
    if not isinstance(anchor, dict) or set(anchor) != {"path", "revision"}:
        raise CanonicalPlanError("canonical-plan anchor is malformed")
    path = _relative_path(anchor["path"])
    revision = anchor["revision"]
    if not isinstance(revision, str) or not revision:
        raise CanonicalPlanError("canonical-plan anchor revision is malformed")
    return {"path": path, "revision": revision}


def _anchored_document(state, anchor):
    document = gitops.show_file(
        state["workspace"], anchor["revision"], anchor["path"]
    )
    if document is None:
        raise CanonicalPlanError(
            "canonical-plan anchor cannot resolve its committed skeleton"
        )
    return document


def anchor_current_plan(state_path, skeleton_path):
    """Atomically project and Git-anchor the plan committed at current HEAD."""
    skeleton_path = _relative_path(skeleton_path)
    with st.exclusive_mutation(state_path, wait=True):
        state = st.load(state_path)
        workspace = state.get("workspace")
        if not isinstance(workspace, str) or not workspace:
            raise CanonicalPlanError("run state has no workspace")
        revision = gitops.head_full_sha(workspace)
        document = gitops.show_file(workspace, revision, skeleton_path)
        if document is None:
            raise CanonicalPlanError(
                "current Git revision does not contain the canonical skeleton"
            )
        previous = _anchor(state)
        anchored_document = None
        if previous is not None:
            if previous["path"] != skeleton_path:
                raise CanonicalPlanError("canonical-plan anchor path cannot change")
            anchored_document = _anchored_document(state, previous)
            if canonical_block_bytes(document) == canonical_block_bytes(
                anchored_document
            ):
                return copy.deepcopy(previous)

        plan = validate_canonical_plan(document, anchored_document)
        anchor = {"path": skeleton_path, "revision": revision}
        state["milestone"]["slices"] = plan["projection"]
        state["milestone"][ANCHOR_KEY] = anchor
        st.save(state_path, state)
        return copy.deepcopy(anchor)


def guarded_dispatch(
    state,
    dispatch,
    *,
    reconciliation_accepted_revision=None,
):
    """Run ``dispatch`` only from the anchored block or its repair context.

    The optional revision is not an admission flag.  It is the concrete
    accepted revision of a reconciliation already opened by its owning later
    boundary; it must be the current anchor.  Ordinary calls always compare the
    worktree block byte-for-byte and never validate or rebaseline drift.
    """
    if not callable(dispatch):
        raise CanonicalPlanError("guarded dispatch requires a callable")
    anchor = _anchor(state)
    if anchor is None:
        raise CanonicalPlanError("canonical plan has not been anchored")
    anchored = _anchored_document(state, anchor)
    anchored_block = canonical_block_bytes(anchored)

    if reconciliation_accepted_revision is not None:
        reconciliation = state["milestone"].get(RECONCILIATION_KEY)
        if (
            not isinstance(reconciliation, dict)
            or reconciliation.get("status") != "open"
            or reconciliation.get("accepted_revision")
            != reconciliation_accepted_revision
            or reconciliation_accepted_revision != anchor["revision"]
        ):
            raise CanonicalPlanDrift(
                "no open accepted-range reconciliation matches the plan anchor"
            )
        return dispatch()

    path = os.path.join(state["workspace"], anchor["path"])
    try:
        with open(path, "rb") as handle:
            current = handle.read()
        current_block = canonical_block_bytes(current)
    except (OSError, CanonicalPlanError) as exc:
        raise CanonicalPlanDrift(
            "canonical plan drift blocks dispatch; the anchor was not changed"
        ) from exc
    if current_block != anchored_block:
        raise CanonicalPlanDrift(
            "canonical plan drift blocks dispatch; the anchor was not changed"
        )
    return dispatch()
