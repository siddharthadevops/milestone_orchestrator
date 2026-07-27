"""Failure classification: recoverable infra errors become typed,
schedulable failures instead of dead stops.

Two-stage chain, never blocking and never authoritative over content:

1. Deterministic pattern table over the failed worker's raw output —
   offline, instant, free. Covers the known families (login, quota with
   a concrete reset time, network, service busy, timeout).
2. Opposite-family LLM classifier as fallback for noisy cases: a tiny
   closed-enum JSON contract; one attempt, its own short timeout, and
   any problem (dead CLI, garbage output, disabled in config) degrades
   to "unknown" — today's plain-failure behavior, untouched.

The classifier picks from an enum and extracts a timestamp; it has no
authority over anything else. Correlated outages (both CLIs down) land
on "unknown" by design.

Types and their operational meaning (consumed by the driver and by the
service auto-resume guard):

  login    unrecoverable without the operator (`claude /login`); never
           auto-resumed, no repair retry (the model never saw the prompt)
  quota    recoverable at a known/parsed reset time (5h windows);
           auto-resume at resume_at
  network  transient connectivity; short in-driver retries first, then
           auto-resume after a near-term backoff
  busy     service overloaded/5xx; same shape as network
  timeout  a configured cap killed the call; auto-resume near-term
  unknown  everything else; requires the operator
"""

import json
import re
from datetime import datetime, timedelta

from . import runners

TYPES = ("login", "quota", "network", "busy", "timeout", "unknown")

# Types the service guard may auto-resume (login/unknown never).
AUTO_RESUMABLE = ("quota", "network", "busy", "timeout")

# Near-term backoff for transient types without an explicit reset time.
TRANSIENT_BACKOFF_MIN = 10

# Patterns are matched only against SHORT texts (real CLI error banners;
# see MAX_CLASSIFIABLE_CHARS): a 4KB review that merely DISCUSSES quota
# or auth handling is content, not an infra error. Bare status codes
# additionally require an error-ish neighbor so "driver.py:429" in a
# stack line cannot read as rate limiting.
_PATTERNS = (
    ("login", (
        r"not logged in",
        r"please run /login",
        r"please log ?in\b",
        r"\b401 unauthorized",
        r"invalid api key",
    )),
    ("quota", (
        r"usage limit",
        r"rate limit",
        r"\bquota\b",
        r"limit reached",
        # The claude CLI states it the other way round — "You've reached
        # your Fable 5 limit. Run /usage-credits to continue" — so
        # `limit reached` misses it and a plain quota stop was typed
        # `unknown`, which the guard re-probes every 15 min instead of
        # parking until the window resets (found live 2026-07-19).
        # BOTH halves of the banner are required. Either one alone also
        # fits ordinary prose ("you've reached your configured retry
        # limit"; "mention /usage-credits in the docs"), and a false quota
        # verdict is worse than none: it puts a CONTENT failure on the
        # guard's auto-resume loop. Under-matching merely falls through to
        # the LLM classifier, so the tight form is the safe one.
        # Anchored to a line/segment start so a real banner OPENS with the
        # sentence, while prose that merely contains both phrases ("Finding:
        # the worker reached your configured retry limit; mention
        # /usage-credits only for quota failures") does not. Two anchors: the
        # bare banner (claude's stdout), and the same banner wrapped by the
        # runner's own no-output RunnerError, whose literal prefix is
        # "stderr tail: " (matching a bare "tail:" also catches the suffix
        # of unrelated words like "Detail:").
        r"(?:^|stderr tail:\s*)\W{0,4}you(?:'ve| have) reached your "
        r"[^.\n]{0,30}\blimit\b[^\n]{0,80}/usage-credits",
        r"out of (free )?credits",
    )),
    ("busy", (
        r"overloaded",
        r"service unavailable",
        r"server busy",
        r"too many requests",
        # Provider capacity banners. These are recognized deterministically
        # because a correlated outage takes the LLM classifier down too —
        # when no family can be asked, the provider's own capacity signal is
        # the only thing left to read. (codex: "Selected model is at
        # capacity. Please try a different model."; Anthropic: overloaded_error)
        r"at capacity",
        r"try a different model",
        r"overloaded_error",
        r"(?:error|status|http)[^\n]{0,24}\b(?:429|503|529)\b",
        r"\b(?:429|503|529)\b[^\n]{0,24}(?:error|unavailable|overload)",
    )),
    ("network", (
        r"\benotfound\b",
        r"\beconnrefused\b",
        r"\beconnreset\b",
        r"\betimedout\b",
        r"getaddrinfo",
        r"fetch failed",
        r"could not connect",
        r"network error",
        r"\bdns\b",
        r"socket hang ?up",
    )),
    # The timeout / stall messages are authored by runners.py itself — a
    # safe self-match, unlike worker prose.
    ("timeout", (
        r"timed out after \d+s",
        # The runner's exact self-authored stall message, numeric parts and
        # all (the numbers may be scientific notation, e.g. 1e-05), so worker
        # prose merely mentioning "stalled" / "frozen worker" cannot
        # masquerade as an auto-resumable infra failure.
        r"stalled: its process tree burned under [\d.eE+-]+s of cpu "
        r"over a [\d.eE+-]+s window \(frozen worker\)",
    )),
)

# Real CLI error banners are short; anything longer is (or contains)
# content and must not be pattern-typed.
MAX_CLASSIFIABLE_CHARS = 600

# Reset-time extraction for quota messages: "resets at 00:37",
# "try again at 3:15 PM", "resets 4pm", "available again at 16:00",
# and codex's dated form "try again at Jul 11th, 2026 12:26 AM" — the
# optional date phrase (month, day, year) between the anchor and the
# clock must be consumed whole, or the year's digits would be read as
# the hour (found live 2026-07-10: the announced 00:26 window fell back
# to the +30min default). The date itself is ignored; parse_resume_at's
# next-occurrence rollover covers it.
_TIME_RE = re.compile(
    r"(?:reset?s?|try again|available again|resumes?)\s*(?:at\s*)?"
    r"(?:[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:\d{4}\s+)?)?"
    r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)?",
    re.IGNORECASE,
)
_RELATIVE_RE = re.compile(
    r"\b(?:in|after)\s+(\d{1,3})\s*"
    r"(hours?\b|hrs?\b|h\b|minutes?\b|mins?\b|m\b)",
    re.IGNORECASE,
)
# A stated non-local timezone we cannot honor: better a cheap 10-minute
# probe than a confidently wrong 24h park.
_FOREIGN_TZ_RE = re.compile(
    r"\b(?:GMT|UTC)[+-]?\d*\b|\([A-Za-z_]+/[A-Za-z_]+\)|\b[PECM][SD]T\b"
)


def classify_text(text):
    """Deterministic pattern classification of ONE text. Returns a type
    or None. Texts longer than MAX_CLASSIFIABLE_CHARS are never typed:
    infra errors are short banners, content is long — length is the
    provenance check that keeps worker prose from cosplaying as infra."""
    lowered = (text or "").strip().lower()
    if not lowered or len(lowered) > MAX_CLASSIFIABLE_CHARS:
        return None
    for type_, patterns in _PATTERNS:
        for pat in patterns:
            if re.search(pat, lowered):
                return type_
    return None


def parse_resume_at(text, now=None):
    """Extract a concrete resume time from a quota-style message.

    Clock times roll over to tomorrow when already past (a 5h window
    that 'resets at 00:37' announced at 23:50 means tonight; announced
    at 01:00 it means tonight too — the NEXT occurrence). Relative
    forms ('in 5 hours') add to now. Returns an ISO string with the
    local offset, or None."""
    if not text:
        return None
    now = now or datetime.now().astimezone()
    if _FOREIGN_TZ_RE.search(text):
        return None
    m = _RELATIVE_RE.search(text)
    if m:
        qty = int(m.group(1))
        unit = m.group(2).lower()
        delta = timedelta(hours=qty) if unit.startswith("h") else \
            timedelta(minutes=qty)
        return (now + delta).strftime("%Y-%m-%dT%H:%M:%S%z")
    for m in _TIME_RE.finditer(text):
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = (m.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            continue  # keep scanning: a later match may be the real time
        candidate = now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.strftime("%Y-%m-%dT%H:%M:%S%z")
    return None


RESUME_MIN_S = 60
RESUME_MAX_S = 24 * 3600


def normalize_resume_at(value, now=None):
    """Canonicalize an operator/classifier-supplied resume_at into the
    ledger format, clamped to [now+1min, now+24h]. Anything unparsable
    (naive strings get the local offset attached) returns None so the
    caller substitutes a sane backoff — a hallucinated or injected
    timestamp must never park a run for days or fire it immediately."""
    if not value or not isinstance(value, str):
        return None
    now = now or datetime.now().astimezone()
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    lo = now + timedelta(seconds=RESUME_MIN_S)
    hi = now + timedelta(seconds=RESUME_MAX_S)
    parsed = min(max(parsed, lo), hi)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S%z")


CLASSIFIER_PROMPT = """You are classifying a FAILED AI-CLI worker call \
for an orchestrator. Below are the raw output(s) of the failed call. \
Decide which infrastructure error class fits best.

Classes:
- "login": the CLI is not authenticated (needs an operator login)
- "quota": a usage/rate limit window; extract the reset time if stated
- "network": connectivity/DNS/socket failure
- "busy": the service is overloaded/unavailable (5xx, capacity)
- "timeout": the call was killed by a time cap
- "unknown": anything else, including content-level garbage

Respond with EXACTLY ONE JSON object, nothing else:
{"error_type": "<one of the classes>",
 "resume_at": null or "an ISO-8601 local timestamp when retrying makes sense",
 "evidence": "<the exact phrase from the output that decided it>"}

RAW OUTPUT(S) OF THE FAILED CALL
--------------------------------
%s
--------------------------------
"""

CLASSIFIER_TIMEOUT_S = 120
_RAW_CLIP = 4000


def llm_classify(runner, family, raw_texts, workspace, on_raw=None,
                 model=None, effort=None):
    """One opposite-family attempt at classifying noisy failure output.
    NEVER raises and never blocks beyond its own timeout: any problem
    returns ("unknown", None, <why>).

    model/effort MUST be the classifier family's resolved profile: a
    command template carrying {model}/{effort} placeholders (codex) cannot
    be built without them, so omitting them killed this stage before it
    ever reached the CLI ("command template uses {model} but no value was
    resolved") and every unmatched failure degraded to `unknown` — the
    whole LLM fallback layer silently dead (found live 2026-07-19).

    on_raw(family, prompt, response_or_error), if given, is invoked
    best-effort with the classifier's prompt and its raw response — or the
    error string when the classifier CALL itself failed. This is the only
    worker call whose output is otherwise never persisted, so without it an
    "unknown" verdict is unauditable (you cannot tell "the classifier was
    itself down" from "the classifier judged it garbage")."""
    joined = "\n---\n".join(
        (t or "")[-_RAW_CLIP:] for t in raw_texts if (t or "").strip()
    )
    if not joined.strip():
        return "unknown", None, "no raw output to classify"
    prompt = CLASSIFIER_PROMPT % joined
    raw = None
    try:
        result = runner.call(
            family, prompt, workspace,
            model=model, effort=effort,
            timeout_override=CLASSIFIER_TIMEOUT_S,
        )
        raw = result.text
        objects = runners.extract_json_objects(result.text)
        matches = [obj for obj in objects if obj.get("error_type") in TYPES]
        if len(matches) != 1:
            reported = [obj.get("error_type") for obj in objects]
            if len(matches) > 1:
                return "unknown", None, "classifier returned multiple valid classifications"
            return "unknown", None, "classifier returned %r" % (reported,)
        obj = matches[0]
        etype = obj["error_type"]
        resume_at = normalize_resume_at(obj.get("resume_at"))
        return etype, resume_at, str(obj.get("evidence") or "")[:300]
    except Exception as exc:  # the classifier must never worsen a failure
        if raw is None:
            raw = "CLASSIFIER CALL FAILED: %s" % exc
        return "unknown", None, "classifier unavailable: %s" % exc
    finally:
        if on_raw is not None:
            try:
                on_raw(family, prompt, raw)
            except Exception:
                pass


def classify_failure(raw_texts, runner=None, opposite_family=None,
                     workspace=None, use_llm=True, on_llm_raw=None,
                     classifier_model=None, classifier_effort=None):
    """Full chain: patterns first, LLM fallback, unknown last.

    Returns (type, resume_at_iso_or_None, evidence). on_llm_raw is forwarded
    to llm_classify to persist the classifier's I/O when the LLM stage runs.
    classifier_model/classifier_effort are the OPPOSITE family's resolved
    profile; without them a placeholder-carrying template cannot be built
    and the LLM stage cannot run at all (see llm_classify).
    """
    for text in raw_texts:
        etype = classify_text(text)
        if etype:
            resume_at = (
                parse_resume_at(text) if etype == "quota" else None
            )
            return etype, resume_at, "pattern match"
    if use_llm and runner is not None and opposite_family:
        return llm_classify(runner, opposite_family, raw_texts, workspace,
                            on_raw=on_llm_raw,
                            model=classifier_model, effort=classifier_effort)
    return "unknown", None, "no pattern matched"
