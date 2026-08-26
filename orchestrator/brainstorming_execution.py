"""Persistent participant execution for product-neutral brainstorming."""

from __future__ import annotations

import hashlib
import os
import time

from orchestrator import brainstorming, pricing, runners, session_repository


class ExecutionRejected(RuntimeError):
    """The durable session or configured executor cannot admit an exchange."""


def validate_discussion_turn_envelope(envelope):
    """Accept the two model-supplied discussion-turn fields; surplus is
    dropped rather than rejected."""
    brainstorming._model_keys(
        envelope,
        ("kind", "markdown"),
        (),
        "discussion_turn",
    )
    if envelope["kind"] != "discussion_turn":
        raise brainstorming.ContractError(
            "discussion_turn.kind must be discussion_turn"
        )
    brainstorming._text(
        envelope["markdown"], "discussion_turn.markdown"
    )
    return brainstorming._json_copy(envelope, "discussion_turn")


class RunnerParticipantExecutor:
    """Bind one resolved executor reference to the shared CLI runner."""

    def __init__(
        self,
        model_family,
        runner,
        model=None,
        effort=None,
        timeout_override=None,
        current_resolver=None,
        fresh_each_call=False,
    ):
        self.model_family = model_family
        self.runner = runner
        self.model = model
        self.effort = effort
        self.timeout_override = timeout_override
        self.current_resolver = current_resolver
        self.fresh_each_call = bool(fresh_each_call)
        # What the LAST resolution reported beside its answer: the default
        # document answered because an input could not be read. Carried on
        # the executor, exactly as the milestone driver carries it on its own
        # dispatch resolver, so the activity entry for this call can say so
        # without the answer growing a fourth key.
        self.staffing_fallback = None
        self.prompt_set_fallback = None

    def prepare_dispatch(self, round_number=1):
        """Resolve optional current settings immediately before one call.

        *round_number* is the discussion round the call belongs to — a
        consumer fact the router keeps no history of, and the one input a
        `step_up` rule reads. The seat itself is fixed when the binding is
        built; only the round moves.
        """
        if self.current_resolver is None:
            return
        current = self.current_resolver(round_number)
        self.staffing_fallback = getattr(
            self.current_resolver, "staffing_fallback", None
        )
        if not isinstance(current, dict):
            raise ExecutionRejected(
                "current participant resolver returned no staffing"
            )
        try:
            family = brainstorming._text(
                current["agent"], "current participant agent"
            )
            model = brainstorming._text(
                current["model"], "current participant model"
            )
            effort = brainstorming._text(
                current["effort"], "current participant effort"
            )
        except (KeyError, brainstorming.ContractError) as exc:
            raise ExecutionRejected(
                "current participant staffing is incomplete"
            ) from exc
        self.model_family = family
        self.model = model
        self.effort = effort

    def supports_continuation(self):
        if self.current_resolver is not None:
            # Current-state milestone seats deliberately start a fresh
            # provider session for each dispatch; their prompts already point
            # to the complete shared transcript. No retained provider binding
            # can therefore freeze a prior family/model selection.
            return True
        return self.runner.supports_session_continuation(self.model_family)

    def start(self, prompt, workspace_path, execution_context):
        return self.runner.start_session(
            self.model_family,
            prompt,
            workspace_path,
            execution_context,
            model=self.model,
            effort=self.effort,
            timeout_override=self.timeout_override,
        )

    def continue_session(
        self,
        session_ref,
        prompt,
        workspace_path,
        execution_context,
    ):
        if self.fresh_each_call:
            return self.runner.start_session(
                self.model_family,
                prompt,
                workspace_path,
                execution_context,
                model=self.model,
                effort=self.effort,
                timeout_override=self.timeout_override,
            )
        return self.runner.continue_session(
            self.model_family,
            session_ref,
            prompt,
            workspace_path,
            execution_context,
            model=self.model,
            effort=self.effort,
            timeout_override=self.timeout_override,
        )

    @staticmethod
    def wait_for_quiescence(result):
        """Confirm the shared runner reaped the supervised local process set."""
        return getattr(result, "worker_quiescent", None) is True


class ParticipantExecution:
    """Run validated exchanges for already-resolved durable participants."""

    def __init__(self, store, executors, failure_classifier=None,
                 billing=None):
        self.store = store
        self.executors = dict(executors)
        self.failure_classifier = failure_classifier
        # How each family is paid for, so a discussion turn's price carries
        # the same two readings the rest of the accounting does. Absent, the
        # declared defaults apply.
        self.billing = dict(billing or {})

    @staticmethod
    def _participant(snapshot, participant_id):
        for participant in snapshot.state["run_config"]["participants"]:
            if participant["id"] == participant_id:
                return participant
        raise ExecutionRejected(
            "participant_id is not in the persisted roster"
        )

    @staticmethod
    def _binding_ref(participant):
        return (
            participant["executor_ref"]
            if participant["delivery"] == "llm"
            else participant["external_ref"]
        )

    @staticmethod
    def _require_status(snapshot, required_status):
        if snapshot is None:
            raise brainstorming.SessionNotFound("brainstorming session")
        if snapshot.state["status"] != required_status:
            raise ExecutionRejected(
                "participant exchanges require a %s session"
                % required_status
            )

    @classmethod
    def _require_running(cls, snapshot):
        cls._require_status(snapshot, "running")

    def _executor(self, participant):
        binding = self.executors.get(self._binding_ref(participant))
        if binding is None:
            raise ExecutionRejected(
                "the persisted executor_ref has no configured binding"
            )
        if (
            participant["delivery"] == "llm"
            and getattr(binding, "current_resolver", None) is None
            and getattr(binding, "model_family", None)
            != participant["model_family"]
        ):
            raise ExecutionRejected(
                "the executor binding model_family does not match the roster"
            )
        supports = getattr(binding, "supports_continuation", None)
        if not callable(supports) or not supports():
            raise ExecutionRejected(
                "the executor binding has no explicit continuation support"
            )
        if not callable(getattr(binding, "start", None)) or not callable(
            getattr(binding, "continue_session", None)
        ):
            raise ExecutionRejected(
                "the executor binding is incomplete"
            )
        return binding

    def _durable_provider_ref(self, snapshot, participant):
        session_ref = snapshot.state.get("participant_sessions", {}).get(
            participant["id"]
        )
        if session_ref is None:
            return None
        return brainstorming.provider_session_ref(
            self._binding_ref(participant), session_ref
        )

    def _require_current_binding(
        self, session_id, participant, provider_ref,
        required_status="running",
    ):
        current = self.store.read(session_id)
        self._require_status(current, required_status)
        durable_ref = self._durable_provider_ref(current, participant)
        if durable_ref != provider_ref:
            raise ExecutionRejected(
                "the durable participant session reference changed"
            )
        return current

    @staticmethod
    def _parse(result, validator=validate_discussion_turn_envelope):
        envelope, closers = runners._extract_contract_output(
            result.text,
            validator,
        )
        # Participant envelopes are not eligible for punctuation recovery;
        # keep this assertion explicit if the shared helper evolves.
        if closers is not None:
            raise brainstorming.ContractError(
                "participant control envelopes cannot use delimiter recovery"
            )
        return envelope

    @staticmethod
    def _result_session_ref(result, expected=None):
        session_ref = getattr(result, "session_ref", None)
        try:
            brainstorming._text(session_ref, "provider session_ref")
        except brainstorming.ContractError as exc:
            raise ExecutionRejected(str(exc)) from exc
        if expected is not None and session_ref != expected:
            raise ExecutionRejected(
                "executor continued a different logical session"
            )
        return session_ref

    @staticmethod
    def _wait_for_quiescence(executor, result):
        waiter = getattr(executor, "wait_for_quiescence", None)
        if not callable(waiter):
            raise ExecutionRejected(
                "the executor binding exposes no worker-quiescence evidence"
            )
        if waiter(result) is not True:
            # The result carries immutable completion evidence. Unknown keeps
            # the ordered acceptance window open, but plain exchanges do not
            # require this stronger proof.
            raise ExecutionRejected(
                "worker quiescence could not be confirmed"
            )

    def _invoke_executor(
        self,
        operation,
        args,
        executor,
        require_quiescence,
        evidence,
    ):
        evidence["quiescent"] = not require_quiescence
        try:
            result = operation(*args)
        except BaseException as exc:
            evidence["quiescent"] = (
                getattr(exc, "worker_quiescent", None) is True
            )
            raise
        if require_quiescence:
            try:
                self._wait_for_quiescence(executor, result)
            except BaseException as exc:
                try:
                    exc.runner_result = result
                except (AttributeError, TypeError):
                    pass
                raise
            evidence["quiescent"] = True
        return result

    def _action_context(self, session_id, participant):
        """Identify the action one physical call belongs to.

        ONE derivation, read by the two seams that need it: the round the
        router is asked for immediately before the call, and the activity
        entry written after it. Returns ``None`` when no coordinator or
        production seam recorded an action, which is how a low-level caller
        exercising :class:`ParticipantExecution` directly stays silent.

        Read afresh per physical call, so the ROUND stays the action's while
        the provider attempt moves: an envelope repair bumps the durable
        attempt before its dispatch (`mark_turn_attempt_envelope_repair`,
        `retry_external_provider`) and the production branch counts what the
        ledger already holds, which is why a repair records its own activity
        instead of reusing the failed call's identity.
        """
        attempt = self.store.read_turn_attempt(session_id)
        if attempt is not None:
            kind = attempt.get("kind", "discussion_turn")
            return {
                "action_id": attempt["token"],
                "provider_attempt": attempt.get("provider_attempt", 1),
                "completed": attempt["completed_turn_count"],
                "kind": kind,
                "stage": (
                    (attempt.get("action_context") or {}).get("stage")
                    if kind == "closure"
                    else "discussion"
                ),
                "production": None,
            }
        intervention = self.store.read_external_intervention(session_id)
        if (
            intervention is not None
            and intervention["participant_id"] == participant["id"]
        ):
            kind = (
                "discussion_turn"
                if intervention["action_kind"] == "discussion_turn"
                else "closure"
            )
            return {
                "action_id": intervention["token"],
                "provider_attempt": intervention["provider_attempt"],
                "completed": intervention["completed_turn_count"],
                "kind": kind,
                "stage": (
                    "discussion" if kind == "discussion_turn" else "vote"
                ),
                "production": None,
            }
        production = self.store.read_task_effect_attempt(session_id)
        if production is None:
            return None
        action_id = "task-production-effect:%s:lead" % production["token"]
        activity = self.store.read_activity(session_id) or {"events": []}
        return {
            "action_id": action_id,
            "provider_attempt": 1 + sum(
                event.get("action_id") == action_id
                for event in activity["events"]
            ),
            "completed": 0,
            "kind": "production_effect",
            "stage": "production",
            "production": production,
        }

    def _action_round(self, session_id, context):
        """The discussion round *context*'s call belongs to.

        The same count the activity entry records and the one the router is
        asked with, so a `step_up` rule and the ledger can never disagree
        about which round ran. A production effect belongs to the round the
        agreement closed on, not to a round of its own.
        """
        state = self.store.read(session_id)
        if state is None:
            raise brainstorming.SessionNotFound(session_id)
        participants = state.state["run_config"]["participants"]
        if context["production"] is not None:
            native_result = state.state.get("result") or {}
            round_number = native_result.get("rounds_used", 1)
            if type(round_number) is not int or round_number <= 0:
                round_number = 1
            return round_number
        if context["kind"] == "discussion_turn":
            return context["completed"] // len(participants) + 1
        return max(1, context["completed"] // len(participants))

    def _record_activity(
        self,
        session_id,
        participant,
        executor,
        started_at,
        result=None,
        status="completed",
        failure_type=None,
        error=None,
    ):
        context = self._action_context(session_id, participant)
        if context is None:
            # Low-level callers may exercise ParticipantExecution without
            # any coordinator or production seam.
            return None
        action_id = context["action_id"]
        provider_attempt = context["provider_attempt"]
        kind = context["kind"]
        stage = context["stage"]
        digest = hashlib.sha256(
            ("%s:%d" % (action_id, provider_attempt)).encode("utf-8")
        ).hexdigest()[:20]
        event_id = "activity-%s" % digest
        duration = (
            getattr(result, "duration_s", None)
            if result is not None
            else None
        )
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            duration = max(0.0, time.time() - started_at)
        raw_text = None
        if result is not None:
            raw_text = getattr(result, "text", None)
        if raw_text is None and error is not None:
            raw_texts = getattr(error, "raw_texts", None)
            if isinstance(raw_texts, (list, tuple)) and raw_texts:
                raw_text = "\n\n--- provider output ---\n\n".join(
                    str(item) for item in raw_texts
                )
            else:
                raw_text = str(error)
        raw_ref = self.store.save_activity_output(
            session_id, event_id, raw_text or ""
        )
        round_number = self._action_round(session_id, context)
        event = {
            "id": event_id,
            "action_id": action_id,
            "provider_attempt": provider_attempt,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "started_at": float(started_at),
            "duration_s": float(duration),
            "kind": kind,
            "stage": stage,
            "round": round_number,
            "participant_id": participant["id"],
            "model_family": executor.model_family,
            "model": getattr(executor, "model", None),
            "effort": getattr(executor, "effort", None),
            "status": status,
            "raw_ref": raw_ref,
        }
        # What actually ran, including the note that the default document
        # answered because the session or its document could not be read.
        fallback = getattr(executor, "staffing_fallback", None)
        if fallback:
            event["staffing_fallback"] = fallback
        prompt_fallback = getattr(executor, "prompt_set_fallback", None)
        if prompt_fallback:
            event["prompt_set_fallback"] = prompt_fallback
        usage_source = result if result is not None else error
        token_usage = runners.normalize_token_usage(
            getattr(usage_source, "token_usage", None)
        )
        if token_usage is not None:
            event["token_usage"] = token_usage
        if getattr(usage_source, "token_usage_partial", False):
            event["token_usage_partial"] = True
        # Discussion turns are worker calls like any other: what they cost
        # belongs in the same record as what they consumed.
        cost = pricing.quote_many(
            executor.model_family,
            getattr(executor, "model", None),
            getattr(usage_source, "cost_payloads", None),
            billing=(self.billing or {}).get(executor.model_family),
        )
        if cost.api_usd is not None and cost.real_usd is not None:
            event["cost"] = cost.as_dict()
        else:
            # Either reading unknown (unpriced model, or a billing mode the
            # config spelled wrong) makes the turn's price unknown. Writing a
            # half-known cost would fail the activity contract outright.
            event["cost_partial"] = True
        prompt_path = getattr(usage_source, "prompt_path", None)
        if isinstance(prompt_path, str) and prompt_path:
            event["prompt_ref"] = os.path.basename(prompt_path)
        if status == "failed":
            event["failure_type"] = failure_type
            error_text = str(error).strip() if error is not None else ""
            event["error"] = (
                error_text or type(error).__name__ or "Unknown failure"
            )[:4000]
        self.store.append_activity(session_id, event)
        return event

    def _invoke_tracked(
        self,
        session_id,
        participant,
        executor,
        operation,
        args,
        require_quiescence,
        evidence,
    ):
        prepare = getattr(executor, "prepare_dispatch", None)
        if callable(prepare):
            # Resolution failure is pre-dispatch: do not manufacture a model
            # call activity record when no provider was invoked.
            #
            # A surfaced staffing condition is RAISED here carrying its
            # exact token, and that raise is the whole of what this seam
            # owes it: from here the condition travels as this discussion's
            # ordinary participant failure, in the discussion's own
            # vocabulary, and the router's tokens are not a second stored
            # or public failure language for Brainstorming to speak.
            #
            # The round is the one the action about to run belongs to, read
            # from the same seams the activity entry reads afterwards. A
            # provider RETRY of the same action is the same discussion round
            # — attempts are not rounds — so a `step_up` rule escalates the
            # seat the discussion is actually on.
            #
            # Nothing is dispatched when that raise happens, and the failure
            # says so itself: the supervising seam retires the durable
            # attempt without manufacturing an activity record — a family, a
            # cost and a token uncertainty — for a call that never ran.
            try:
                context = self._action_context(session_id, participant)
                prepare(
                    1 if context is None
                    else self._action_round(session_id, context)
                )
            except BaseException as exc:
                try:
                    exc.brainstorming_dispatch_refused = True
                except (AttributeError, TypeError):
                    pass
                raise
        started_at = time.time()
        try:
            result = self._invoke_executor(
                operation,
                args,
                executor,
                require_quiescence,
                evidence,
            )
        except BaseException as exc:
            self._record_activity(
                session_id,
                participant,
                executor,
                started_at,
                result=getattr(exc, "runner_result", None),
                status="failed",
                failure_type="execution",
                error=exc,
            )
            raise
        return result, started_at

    def exchange(
        self,
        session_id,
        participant_id,
        prompt,
        execution_context,
    ):
        """Return one valid envelope plus its technical runner result."""
        return self._exchange(
            session_id,
            participant_id,
            prompt,
            execution_context,
            require_quiescence=False,
            validator=validate_discussion_turn_envelope,
        )

    def exchange_quiescent(
        self,
        session_id,
        participant_id,
        prompt,
        execution_context,
        before_repair=None,
        after_validate=None,
    ):
        """Return an envelope only after all supervised local work is quiet."""
        return self._exchange(
            session_id,
            participant_id,
            prompt,
            execution_context,
            require_quiescence=True,
            validator=validate_discussion_turn_envelope,
            before_repair=before_repair,
            after_validate=after_validate,
        )

    def exchange_prepared_quiescent(
        self,
        session_id,
        participant_id,
        prepare_call,
        execution_context,
        before_repair=None,
        after_validate=None,
    ):
        """Resolve prompt and bound validator afresh for each attempt."""
        if not callable(prepare_call):
            raise brainstorming.ContractError(
                "prepared exchange requires a callable preparation boundary"
            )
        return self._exchange(
            session_id,
            participant_id,
            None,
            execution_context,
            require_quiescence=True,
            validator=None,
            before_repair=before_repair,
            after_validate=after_validate,
            prepare_call=prepare_call,
        )

    @staticmethod
    def _complete_prepared_attempt(prepared, result):
        complete = getattr(prepared, "complete", None)
        if complete is None:
            return None
        if not callable(complete):
            raise ExecutionRejected(
                "prepared repository completion is not callable"
            )
        outcome = complete()
        if not isinstance(outcome, dict) or "accept_reply" not in outcome:
            raise ExecutionRejected(
                "prepared repository completion returned no disposition"
            )
        result.repository_turn = outcome
        if not outcome["accept_reply"]:
            error = session_repository.ReadOnlyTurnInvalidated(
                "read-only repository mutation restored; repeat the seat"
            )
            error.repository_turn = outcome
            error.raw_texts = [getattr(result, "text", "")]
            raise error
        return outcome

    def exchange_control_quiescent(
        self,
        session_id,
        participant_id,
        prompt,
        execution_context,
        validator,
        before_repair=None,
        after_validate=None,
    ):
        """Continue one participant session with a supplied control contract."""
        if not callable(validator):
            raise brainstorming.ContractError(
                "control envelope validator must be callable"
            )
        if before_repair is not None and not callable(before_repair):
            raise brainstorming.ContractError(
                "control before_repair check must be callable"
            )
        if after_validate is not None and not callable(after_validate):
            raise brainstorming.ContractError(
                "control after_validate check must be callable"
            )
        return self._exchange(
            session_id,
            participant_id,
            prompt,
            execution_context,
            require_quiescence=True,
            validator=validator,
            before_repair=before_repair,
            after_validate=after_validate,
        )

    def production_effect(
        self,
        session_id,
        prompt,
        execution_context,
        validator,
    ):
        """Apply one accepted agreement through its resolved lead seat."""
        if not callable(validator):
            raise brainstorming.ContractError(
                "production envelope validator must be callable"
            )
        snapshot = self.store.read(session_id)
        self._require_status(snapshot, "success")
        leads = [
            participant
            for participant in snapshot.state["run_config"]["participants"]
            if participant.get("role") == "initial_position"
            and participant.get("delivery") == "llm"
        ]
        if len(leads) != 1:
            raise ExecutionRejected(
                "production requires one resolved Initial Position lead"
            )
        return self._exchange(
            session_id,
            leads[0]["id"],
            prompt,
            execution_context,
            require_quiescence=True,
            validator=validator,
            required_status="success",
        )

    def _exchange(
        self,
        session_id,
        participant_id,
        prompt,
        execution_context,
        require_quiescence,
        validator,
        before_repair=None,
        after_validate=None,
        required_status="running",
        prepare_call=None,
    ):
        if after_validate is not None and not callable(after_validate):
            raise brainstorming.ContractError(
                "after_validate check must be callable"
            )
        evidence = {"quiescent": True}
        try:
            return self._exchange_with_evidence(
                session_id,
                participant_id,
                prompt,
                execution_context,
                require_quiescence,
                validator,
                evidence,
                before_repair,
                after_validate,
                required_status,
                prepare_call,
            )
        except BaseException as exc:
            if require_quiescence and evidence["quiescent"]:
                try:
                    exc.worker_quiescent = True
                except (AttributeError, TypeError):
                    pass
                if (
                    callable(self.failure_classifier)
                    and isinstance(
                        exc,
                        (runners.RunnerError, runners.WorkerProtocolError),
                    )
                ):
                    try:
                        snapshot = self.store.read(session_id)
                        participant = self._participant(
                            snapshot, participant_id
                        )
                        executor = self._executor(participant)
                        classification = self.failure_classifier(
                            session_id, participant, executor, exc
                        )
                        if isinstance(classification, dict):
                            exc.brainstorming_failure_classification = (
                                classification
                            )
                    except Exception:
                        # Classification is advisory. Its own failure must not
                        # replace the participant failure being recovered.
                        pass
            raise

    def _exchange_with_evidence(
        self,
        session_id,
        participant_id,
        prompt,
        execution_context,
        require_quiescence,
        validator,
        evidence,
        before_repair,
        after_validate,
        required_status,
        prepare_call,
    ):
        brainstorming._text(participant_id, "participant_id")
        snapshot = self.store.read(session_id)
        self._require_status(snapshot, required_status)
        participant = self._participant(snapshot, participant_id)
        executor = self._executor(participant)
        if prepare_call is not None:
            try:
                prepared = prepare_call(None)
                prompt = prepared.prompt
                validator = prepared.validate
                executor.prompt_set_fallback = (
                    prepared.prompt_set_fallback
                )
            except BaseException as exc:
                try:
                    exc.brainstorming_dispatch_refused = True
                except (AttributeError, TypeError):
                    pass
                raise
        else:
            prepared = None
            executor.prompt_set_fallback = None
        brainstorming._text(prompt, "prompt")
        if not callable(validator):
            raise ExecutionRejected(
                "participant reply validator is unavailable"
            )
        if require_quiescence and not callable(
            getattr(executor, "wait_for_quiescence", None)
        ):
            raise ExecutionRejected(
                "the executor binding exposes no worker-quiescence evidence"
            )
        workspace_path = snapshot.state["request"]["workspace_path"]
        fresh_each_call = bool(
            getattr(executor, "fresh_each_call", False)
        )
        provider_ref = (
            None if fresh_each_call
            else self._durable_provider_ref(snapshot, participant)
        )

        if provider_ref is None:
            result, started_at = self._invoke_tracked(
                session_id,
                participant,
                executor,
                executor.start,
                (prompt, workspace_path, execution_context),
                require_quiescence,
                evidence,
            )
            try:
                provider_ref = self._result_session_ref(result)
                if not fresh_each_call:
                    bound = self.store.bind_participant_session(
                        session_id,
                        snapshot.revision,
                        participant_id,
                        provider_ref,
                    )
                    provider_ref = self._durable_provider_ref(
                        bound, participant
                    )
            except BaseException as exc:
                self._record_activity(
                    session_id, participant, executor, started_at,
                    result=result, status="failed",
                    failure_type="execution", error=exc,
                )
                raise
        else:
            result, started_at = self._invoke_tracked(
                session_id,
                participant,
                executor,
                executor.continue_session,
                (
                    provider_ref,
                    prompt,
                    workspace_path,
                    execution_context,
                ),
                require_quiescence,
                evidence,
            )
            try:
                self._result_session_ref(result, expected=provider_ref)
            except BaseException as exc:
                self._record_activity(
                    session_id, participant, executor, started_at,
                    result=result, status="failed",
                    failure_type="execution", error=exc,
                )
                raise

        if prepared is not None:
            try:
                self._complete_prepared_attempt(prepared, result)
            except BaseException as exc:
                self._record_activity(
                    session_id, participant, executor, started_at,
                    result=result, status="failed",
                    failure_type="acceptance", error=exc,
                )
                raise

        try:
            envelope = self._parse(result, validator)
            if fresh_each_call:
                self._require_status(
                    self.store.read(session_id), required_status
                )
            else:
                self._require_current_binding(
                    session_id,
                    participant,
                    provider_ref,
                    required_status=required_status,
                )
        except (ValueError, brainstorming.ContractError) as exc:
            self._record_activity(
                session_id, participant, executor, started_at,
                result=result, status="failed",
                failure_type="protocol", error=exc,
            )
            first_error = str(exc)
        except BaseException as exc:
            self._record_activity(
                session_id, participant, executor, started_at,
                result=result, status="failed",
                failure_type="execution", error=exc,
            )
            raise
        else:
            try:
                if after_validate is not None:
                    after_validate(envelope)
            except BaseException as exc:
                self._record_activity(
                    session_id,
                    participant,
                    executor,
                    started_at,
                    result=result,
                    status="failed",
                    failure_type="acceptance",
                    error=exc,
                )
                raise
            self._record_activity(
                session_id, participant, executor, started_at, result=result
            )
            return envelope, result

        # The first strike is repaired only after re-reading the exact durable
        # binding and lifecycle. A terminalized session receives no control
        # exchange, and the repair can never select a fresh/latest session.
        if before_repair is not None:
            try:
                before_repair()
            except runners.WorkerProtocolError as exc:
                if not getattr(exc, "raw_texts", None):
                    exc.raw_texts = [result.text]
                raise
        if fresh_each_call:
            self._require_status(self.store.read(session_id), required_status)
        else:
            self._require_current_binding(
                session_id,
                participant,
                provider_ref,
                required_status=required_status,
            )
        if prepare_call is None:
            repair_prompt = prompt + (runners.REPAIR_SUFFIX % first_error)
            repair_validator = validator
            repair_prepared = None
        else:
            try:
                repair_prepared = prepare_call(first_error)
                repair_prompt = repair_prepared.prompt
                repair_validator = repair_prepared.validate
                executor.prompt_set_fallback = (
                    repair_prepared.prompt_set_fallback
                )
            except BaseException as exc:
                try:
                    exc.brainstorming_dispatch_refused = True
                except (AttributeError, TypeError):
                    pass
                raise
            brainstorming._text(repair_prompt, "repair prompt")
            if not callable(repair_validator):
                raise ExecutionRejected(
                    "participant repair validator is unavailable"
                )
        result2, started_at2 = self._invoke_tracked(
            session_id,
            participant,
            executor,
            executor.start if fresh_each_call else executor.continue_session,
            (
                (repair_prompt, workspace_path, execution_context)
                if fresh_each_call else
                (
                    provider_ref,
                    repair_prompt,
                    workspace_path,
                    execution_context,
                )
            ),
            require_quiescence,
            evidence,
        )
        try:
            self._result_session_ref(
                result2,
                expected=None if fresh_each_call else provider_ref,
            )
        except BaseException as exc:
            self._record_activity(
                session_id, participant, executor, started_at2,
                result=result2, status="failed",
                failure_type="execution", error=exc,
            )
            raise
        if repair_prepared is not None:
            try:
                self._complete_prepared_attempt(repair_prepared, result2)
            except BaseException as exc:
                self._record_activity(
                    session_id, participant, executor, started_at2,
                    result=result2, status="failed",
                    failure_type="acceptance", error=exc,
                )
                raise
        try:
            envelope = self._parse(result2, repair_validator)
            if fresh_each_call:
                self._require_status(
                    self.store.read(session_id), required_status
                )
            else:
                self._require_current_binding(
                    session_id,
                    participant,
                    provider_ref,
                    required_status=required_status,
                )
        except (ValueError, brainstorming.ContractError) as exc:
            self._record_activity(
                session_id, participant, executor, started_at2,
                result=result2, status="failed",
                failure_type="protocol", error=exc,
            )
            raise runners.WorkerProtocolError(
                "executor %s produced a contract-violating participant envelope "
                "twice: first error: %s; second error: %s"
                % (self._binding_ref(participant), first_error, exc),
                raw_texts=[result.text, result2.text],
            )
        except BaseException as exc:
            self._record_activity(
                session_id, participant, executor, started_at2,
                result=result2, status="failed",
                failure_type="execution", error=exc,
            )
            raise
        else:
            try:
                if after_validate is not None:
                    after_validate(envelope)
            except BaseException as exc:
                self._record_activity(
                    session_id,
                    participant,
                    executor,
                    started_at2,
                    result=result2,
                    status="failed",
                    failure_type="acceptance",
                    error=exc,
                )
                raise
            self._record_activity(
                session_id, participant, executor, started_at2, result=result2
            )
            result2.repair = {
                "error": first_error,
                "raw_text": result.text,
                "duration_s": result.duration_s,
                "token_usage": getattr(result, "token_usage", None),
                "token_usage_partial": bool(
                    getattr(result, "token_usage_partial", False)
                    or getattr(result, "token_usage", None) is None
                ),
            }
            return envelope, result2
