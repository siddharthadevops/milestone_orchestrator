"""Persistent participant execution for product-neutral brainstorming."""

from __future__ import annotations

import hashlib
import os
import time

from orchestrator import brainstorming, runners


class ExecutionRejected(RuntimeError):
    """The durable session or configured executor cannot admit an exchange."""


def validate_discussion_turn_envelope(envelope):
    """Accept exactly the two model-supplied discussion-turn fields."""
    brainstorming._exact_keys(
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
    ):
        self.model_family = model_family
        self.runner = runner
        self.model = model
        self.effort = effort
        self.timeout_override = timeout_override

    def supports_continuation(self):
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

    def __init__(self, store, executors):
        self.store = store
        self.executors = dict(executors)

    @staticmethod
    def _participant(snapshot, participant_id):
        for participant in snapshot.state["run_config"]["participants"]:
            if participant["id"] == participant_id:
                return participant
        raise ExecutionRejected(
            "participant_id is not in the persisted roster"
        )

    @staticmethod
    def _require_running(snapshot):
        if snapshot is None:
            raise brainstorming.SessionNotFound("brainstorming session")
        if snapshot.state["status"] != "running":
            raise ExecutionRejected(
                "participant exchanges require a running session"
            )

    def _executor(self, participant):
        binding = self.executors.get(participant["executor_ref"])
        if binding is None:
            raise ExecutionRejected(
                "the persisted executor_ref has no configured binding"
            )
        if getattr(binding, "model_family", None) != participant["model_family"]:
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
            participant["executor_ref"], session_ref
        )

    def _require_current_binding(
        self, session_id, participant, provider_ref
    ):
        current = self.store.read(session_id)
        self._require_running(current)
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
        attempt = self.store.read_turn_attempt(session_id)
        if attempt is None:
            # Low-level callers may exercise ParticipantExecution without the
            # lifecycle coordinator. Orchestrated calls always have an
            # admitted turn attempt, which is the durable identity required
            # by the operational ledger.
            return None
        action_id = attempt["token"]
        provider_attempt = attempt.get("provider_attempt", 1)
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
        state = self.store.read(session_id)
        if state is None:
            raise brainstorming.SessionNotFound(session_id)
        participants = state.state["run_config"]["participants"]
        completed = attempt["completed_turn_count"]
        kind = attempt.get("kind", "discussion_turn")
        stage = (
            (attempt.get("action_context") or {}).get("stage")
            if kind == "closure"
            else "discussion"
        )
        round_number = (
            completed // len(participants) + 1
            if kind == "discussion_turn"
            else max(1, completed // len(participants))
        )
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
            "model_family": participant["model_family"],
            "model": getattr(executor, "model", None),
            "effort": getattr(executor, "effort", None),
            "status": status,
            "raw_ref": raw_ref,
        }
        prompt_path = getattr(result, "prompt_path", None)
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
        )

    def exchange_control_quiescent(
        self,
        session_id,
        participant_id,
        prompt,
        execution_context,
        validator,
        before_repair=None,
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
        return self._exchange(
            session_id,
            participant_id,
            prompt,
            execution_context,
            require_quiescence=True,
            validator=validator,
            before_repair=before_repair,
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
    ):
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
            )
        except BaseException as exc:
            if require_quiescence and evidence["quiescent"]:
                try:
                    exc.worker_quiescent = True
                except (AttributeError, TypeError):
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
    ):
        brainstorming._text(participant_id, "participant_id")
        brainstorming._text(prompt, "prompt")
        snapshot = self.store.read(session_id)
        self._require_running(snapshot)
        participant = self._participant(snapshot, participant_id)
        executor = self._executor(participant)
        if require_quiescence and not callable(
            getattr(executor, "wait_for_quiescence", None)
        ):
            raise ExecutionRejected(
                "the executor binding exposes no worker-quiescence evidence"
            )
        workspace_path = snapshot.state["request"]["workspace_path"]
        provider_ref = self._durable_provider_ref(snapshot, participant)

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
                bound = self.store.bind_participant_session(
                    session_id,
                    snapshot.revision,
                    participant_id,
                    provider_ref,
                )
                provider_ref = self._durable_provider_ref(bound, participant)
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

        try:
            envelope = self._parse(result, validator)
            self._require_current_binding(
                session_id, participant, provider_ref
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
            self._record_activity(
                session_id, participant, executor, started_at,
                result=result,
            )
            return envelope, result

        # The first strike is repaired only after re-reading the exact durable
        # binding and lifecycle. A terminalized session receives no control
        # exchange, and the repair can never select a fresh/latest session.
        if before_repair is not None:
            before_repair()
        self._require_current_binding(
            session_id, participant, provider_ref
        )
        repair_prompt = prompt + (runners.REPAIR_SUFFIX % first_error)
        result2, started_at2 = self._invoke_tracked(
            session_id,
            participant,
            executor,
            executor.continue_session,
            (
                provider_ref,
                repair_prompt,
                workspace_path,
                execution_context,
            ),
            require_quiescence,
            evidence,
        )
        try:
            self._result_session_ref(result2, expected=provider_ref)
        except BaseException as exc:
            self._record_activity(
                session_id, participant, executor, started_at2,
                result=result2, status="failed",
                failure_type="execution", error=exc,
            )
            raise
        try:
            envelope = self._parse(result2, validator)
            self._require_current_binding(
                session_id, participant, provider_ref
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
                % (participant["executor_ref"], first_error, exc),
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
            self._record_activity(
                session_id, participant, executor, started_at2,
                result=result2,
            )
            result2.repair = {
                "error": first_error,
                "raw_text": result.text,
                "duration_s": result.duration_s,
            }
            return envelope, result2
