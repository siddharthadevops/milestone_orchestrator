"""Persist provider conversations independently of task checkpoints."""

from . import kvstore, runners


def _retain_conversation(store, key, previous, outcome):
    """Keep a seat's provider reference, including rejected output.

    Separate KV entries let parallel workers save their conversations without
    overwriting the task checkpoint or each other's reference.
    """
    if getattr(outcome, "provider_dispatch_started", None) is False and not getattr(
        outcome, "completed_attempt_before_dispatch_failure", False
    ):
        return
    family = getattr(outcome, "resolved_family", None)
    reference = getattr(outcome, "session_ref", None)
    if not reference and previous and family == previous["family"]:
        reference = previous["session_ref"]
    if not isinstance(reference, str) or not reference.strip():
        return
    saved = {"family": family, "session_ref": reference}
    if family == "codex":
        same_session = previous and previous["family"] == family and (
            previous["session_ref"] == reference
        )
        cumulative = runners.normalize_token_usage(
            getattr(outcome, "session_token_usage", None)
        )
        delta = bool(getattr(outcome, "token_usage_is_delta", False))
        # Without an explicit snapshot, neither a combined failure's totals
        # nor just the final repair turn establish the session's full usage.
        fallback_safe = not (
            getattr(outcome, "session_accounting_is_aggregate", False)
            or getattr(outcome, "repair", None)
        )
        usage = runners.normalize_token_usage(getattr(outcome, "token_usage", None))
        if cumulative is None and fallback_safe:
            if not same_session:
                cumulative = usage
            elif delta and previous.get("token_usage") is not None and usage is not None:
                cumulative = runners.add_token_usage(previous["token_usage"], usage)
        cost = getattr(outcome, "session_cost_payload", None)
        if cost is None and not same_session and not delta and fallback_safe:
            payloads = getattr(outcome, "cost_payloads", None) or []
            cost = payloads[-1] if payloads else None
        saved.update(token_usage=cumulative, cost_payload=cost)
    store.put(key, saved)


def call_worker(store, key, group, runner, *args, **kwargs):
    """Start or continue this seat, retaining its latest provider accounting."""
    previous = store.get(key)
    if previous is kvstore.ABSENT:
        previous = None
    seed_usage = getattr(runner, "seed_codex_session_usage", None)
    if previous and previous["family"] == "codex" and callable(seed_usage):
        seed_usage(
            previous["session_ref"], previous.get("token_usage"),
            cost_payload=previous.get("cost_payload"),
        )
    try:
        reply, result = group.call_worker(
            runner, *args, **kwargs,
            start_session=previous is None,
            session_ref=previous["session_ref"] if previous else None,
            continuation_family=previous["family"] if previous else None,
        )
    except Exception as exc:
        _retain_conversation(store, key, previous, exc)
        raise
    _retain_conversation(store, key, previous, result)
    return reply, result
