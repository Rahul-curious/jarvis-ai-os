from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domains.agents.errors import AgentLifecycleError, AgentValidationError
from app.domains.agents.models import AgentArtifact, AgentEvent
from app.domains.agents.policies import AgentLimits, AgentPolicy
from app.domains.agents.schemas import (
    AgentArtifactCreateRequest,
    AgentDefinitionCreateRequest,
    AgentRunCreateRequest,
    AgentRunStatus,
    AgentStepCreateRequest,
)


def test_definition_and_run_schemas_strip_strings_and_preserve_metadata() -> None:
    definition = AgentDefinitionCreateRequest(
        agent_key="  assistant  ",
        name="  Assistant  ",
        agent_type="  assistant  ",
        description="  Controlled assistant  ",
        configuration={"mode": "grounded"},
    )
    run = AgentRunCreateRequest(
        agent_type=" assistant ",
        task=" Summarize the deployment plan. ",
        input_metadata={"source": "test"},
    )

    assert definition.agent_key == "assistant"
    assert definition.name == "Assistant"
    assert definition.description == "Controlled assistant"
    assert run.task == "Summarize the deployment plan."
    assert run.input_metadata == {"source": "test"}


def test_blank_required_schema_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentDefinitionCreateRequest(agent_key=" ", name="Assistant", agent_type="assistant")

    with pytest.raises(ValidationError):
        AgentRunCreateRequest(agent_type="assistant", task=" ")


def test_policy_enforces_metadata_limits_and_lifecycle_transitions() -> None:
    policy = AgentPolicy(AgentLimits(max_metadata_keys=1, max_metadata_bytes=20))

    with pytest.raises(AgentValidationError):
        policy.validate_run_create(
            AgentRunCreateRequest(
                agent_type="assistant",
                task="A valid task",
                input_metadata={"one": 1, "two": 2},
            )
        )

    policy.validate_status_transition(
        current_status=AgentRunStatus.requested,
        target_status=AgentRunStatus.validating,
    )

    with pytest.raises(AgentLifecycleError):
        policy.validate_status_transition(
            current_status=AgentRunStatus.succeeded,
            target_status=AgentRunStatus.running,
        )


def test_policy_enforces_step_and_artifact_limits() -> None:
    policy = AgentPolicy(AgentLimits(max_artifact_size_bytes=10))
    policy.validate_step_create(
        AgentStepCreateRequest(
            step_index=0,
            step_type="plan",
            name="Plan task",
        )
    )

    with pytest.raises(AgentValidationError):
        policy.validate_artifact_size(11)

    artifact = AgentArtifactCreateRequest(
        artifact_type="report",
        name="report.txt",
        size_bytes=10,
    )
    assert artifact.size_bytes == 10


def test_event_and_artifact_metadata_use_the_persisted_column_name() -> None:
    assert "metadata" in AgentEvent.__table__.c
    assert "event_metadata" not in AgentEvent.__table__.c
    assert "metadata" in AgentArtifact.__table__.c
    assert "artifact_metadata" not in AgentArtifact.__table__.c
