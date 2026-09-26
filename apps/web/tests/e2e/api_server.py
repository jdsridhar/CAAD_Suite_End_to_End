from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import uvicorn

from caddsuite.api.provenance import create_app
from caddsuite.application.handlers import StageHandlerRegistration, StageHandlerRegistry
from caddsuite.contracts.evidence import Candidate
from caddsuite.validation.decisions import DecisionOption, DecisionRequest
from caddsuite.workflow.capabilities import CapabilityInput, StageCapability
from caddsuite.workflow.scheduler import DecisionRequired, TaskInvocation


class DecisionHandler:
    adapter_id = "e2e.decision"
    adapter_version = "1.0.0"
    engine_version = "test-fixture"

    def subject_key(self, _scope: str, _value: object) -> str:
        return "browser-candidate"

    def artifact_hashes(self, inputs: object) -> dict[str, str]:
        if not isinstance(inputs, dict):
            raise TypeError("expected normalized contract inputs")
        canonical = json.dumps(
            {
                name: [item.model_dump(mode="json") for item in values]
                for name, values in inputs.items()
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {"normalized_input": hashlib.sha256(canonical).hexdigest()}

    def gate_context(self, _inputs: object) -> tuple[dict[str, object], frozenset[str]]:
        return {}, frozenset()

    def execute(self, invocation: TaskInvocation) -> Candidate:
        candidate = invocation.inputs["candidate"][0]
        if not isinstance(candidate, Candidate):
            raise TypeError("candidate input has the wrong contract")
        if not invocation.decisions:
            raise DecisionRequired(
                DecisionRequest(
                    issue_code="E2E.REVIEW_CANDIDATE",
                    question="Choose how to handle this candidate.",
                    options=(
                        DecisionOption(
                            key="continue",
                            label="Continue candidate",
                            consequence="Continue to the next workflow stage.",
                        ),
                        DecisionOption(
                            key="stop",
                            label="Stop candidate",
                            consequence="Do not continue this candidate.",
                        ),
                    ),
                )
            )
        if tuple(item.chosen_key for item in invocation.decisions) != ("continue",):
            raise ValueError("the browser fixture only accepts the continue choice")
        return candidate


class DecisionPlugin:
    plugin_id = "e2e.decision"
    version = "1.0.0"

    def registrations(self) -> tuple[StageHandlerRegistration, ...]:
        return (
            StageHandlerRegistration(
                capability=StageCapability(
                    kind="e2e.review_candidate",
                    inputs=(CapabilityInput(name="candidate", contracts=("candidate/1.0",)),),
                    outputs=("candidate/1.0",),
                ),
                factory=lambda _stage, _services: DecisionHandler(),
            ),
        )


_FIXTURE_CREDENTIAL = "browser-e2e-token"

app = create_app(
    data_root=Path(tempfile.mkdtemp(prefix="caddsuite-browser-e2e-")),
    token=_FIXTURE_CREDENTIAL,
    allowed_origins=("http://127.0.0.1:5174",),
    stage_registry=StageHandlerRegistry((DecisionPlugin(),)),
)
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
