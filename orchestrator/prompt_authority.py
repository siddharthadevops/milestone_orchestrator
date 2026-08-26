"""Small shared helpers for current mutable prompt authority."""

from __future__ import annotations

import copy
import json

from . import prompt_router


def read_mutable_amendments(path):
    """Read one complete structurally valid operator-amendment source."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError, UnicodeError) as exc:
        raise prompt_router.PromptRouterError(
            "current mutable operator amendments are unavailable: %s" % exc
        ) from exc
    raw = document.get("amendments") if isinstance(document, dict) else None
    if not isinstance(raw, list):
        raise prompt_router.PromptRouterError(
            "current mutable operator amendments must be an array"
        )
    amendments = []
    for item in raw:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("text"), str)
            or not item["text"].strip()
        ):
            raise prompt_router.PromptRouterError(
                "current mutable operator amendments contain an invalid entry"
            )
        amendment = copy.deepcopy(item)
        amendment.pop("authority", None)
        amendments.append(amendment)
    return amendments


def current_amendments(operator, accepted=()):
    """Render the unconditional complete replacement block for one attempt."""
    if not isinstance(operator, (list, tuple)):
        raise prompt_router.PromptRouterError(
            "current amendments must be a sequence"
        )
    if not isinstance(accepted, (list, tuple)):
        raise prompt_router.PromptRouterError(
            "accepted amendments must be a sequence"
        )
    groups = ([], [])
    for index, source in enumerate((operator, accepted)):
        for item in source:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("text"), str)
                or not item["text"].strip()
            ):
                raise prompt_router.PromptRouterError(
                    "current amendments contain a malformed entry"
                )
            groups[index].append(copy.deepcopy(item))

    lines = [
        "CURRENT MUTABLE OPERATOR AMENDMENTS (complete replacement set)",
        "This set replaces every mutable operator amendment shown earlier.",
    ]
    if groups[0]:
        for item in groups[0]:
            lines.append(
                "[%s] %s" % (str(item.get("id") or "?"), item["text"].strip())
            )
    else:
        lines.append("CURRENT MUTABLE OPERATOR AMENDMENTS: none.")
    if groups[1]:
        lines.extend((
            "",
            "ACCEPTED BRAINSTORMING DESIGN AMENDMENTS (append-only)",
        ))
        for item in groups[1]:
            lines.append(
                "[%s]\n%s" % (str(item.get("id") or "?"), item["text"])
            )
    return "\n".join(lines)
