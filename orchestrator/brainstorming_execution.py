"""Persistent participant execution for product-neutral brainstorming."""

from __future__ import annotations

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
    def _parse(result):
        envelope, closers = runners._extract_contract_output(
            result.text,
            validate_discussion_turn_envelope,
        )
        # Discussion envelopes are not eligible for punctuation recovery;
        # keep this assertion explicit if the shared helper evolves.
        if closers is not None:
            raise brainstorming.ContractError(
                "discussion_turn cannot use delimiter recovery"
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

    def exchange(
        self,
        session_id,
        participant_id,
        prompt,
        execution_context,
    ):
        """Return one valid envelope plus its technical runner result."""
        brainstorming._text(participant_id, "participant_id")
        brainstorming._text(prompt, "prompt")
        snapshot = self.store.read(session_id)
        self._require_running(snapshot)
        participant = self._participant(snapshot, participant_id)
        executor = self._executor(participant)
        workspace_path = snapshot.state["request"]["workspace_path"]
        provider_ref = self._durable_provider_ref(snapshot, participant)

        if provider_ref is None:
            result = executor.start(
                prompt, workspace_path, execution_context
            )
            provider_ref = self._result_session_ref(result)
            bound = self.store.bind_participant_session(
                session_id,
                snapshot.revision,
                participant_id,
                provider_ref,
            )
            provider_ref = self._durable_provider_ref(bound, participant)
        else:
            result = executor.continue_session(
                provider_ref,
                prompt,
                workspace_path,
                execution_context,
            )
            self._result_session_ref(result, expected=provider_ref)

        try:
            envelope = self._parse(result)
            self._require_current_binding(
                session_id, participant, provider_ref
            )
            return envelope, result
        except (ValueError, brainstorming.ContractError) as exc:
            first_error = str(exc)

        # The first strike is repaired only after re-reading the exact durable
        # binding and lifecycle. A terminalized session receives no control
        # exchange, and the repair can never select a fresh/latest session.
        self._require_current_binding(
            session_id, participant, provider_ref
        )
        repair_prompt = prompt + (runners.REPAIR_SUFFIX % first_error)
        result2 = executor.continue_session(
            provider_ref,
            repair_prompt,
            workspace_path,
            execution_context,
        )
        self._result_session_ref(result2, expected=provider_ref)
        try:
            envelope = self._parse(result2)
            self._require_current_binding(
                session_id, participant, provider_ref
            )
            result2.repair = {
                "error": first_error,
                "raw_text": result.text,
                "duration_s": result.duration_s,
            }
            return envelope, result2
        except (ValueError, brainstorming.ContractError) as exc:
            raise runners.WorkerProtocolError(
                "executor %s produced a contract-violating discussion turn "
                "twice: first error: %s; second error: %s"
                % (participant["executor_ref"], first_error, exc),
                raw_texts=[result.text, result2.text],
            )
