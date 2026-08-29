from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.dependencies import get_agent_runtime
from app.domains.agents.runtime import (
    AgentRuntime,
    RuntimeAgentDefinition,
    RuntimeContext,
    RuntimeEvent,
    RuntimeResult,
    RuntimeStatus,
)
from app.domains.agents.schemas import AgentRunCreateRequest
from app.domains.agents.services import AgentRunService
from app.domains.governance.models import AuditLog
from app.domains.identity.models import User


class SuccessfulRuntime(AgentRuntime):
    def __init__(self) -> None:
        self.calls: list[tuple[RuntimeAgentDefinition, RuntimeContext]] = []

    async def execute(
        self,
        *,
        definition: RuntimeAgentDefinition,
        context: RuntimeContext,
    ) -> RuntimeResult:
        self.calls.append((definition, context))
        now = datetime.now(UTC)
        return RuntimeResult(
            run_id=context.run_id,
            status=RuntimeStatus.succeeded,
            events=(
                RuntimeEvent(
                    sequence=0,
                    event_type="runtime.completed",
                    status=RuntimeStatus.succeeded,
                    message="Runtime completed",
                    metadata={"backend": "test"},
                ),
            ),
            started_at=now,
            completed_at=now,
            output_text="Agent run completed by the test runtime.",
            output_metadata={"backend": "test-runtime"},
        )

    async def cancel(self, run_id: uuid.UUID) -> bool:
        return False


def _register(
    client: TestClient,
    *,
    email: str = "agent-api@example.com",
    full_name: str = "Agent API User",
) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": full_name,
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201, response.text


def _run_payload() -> dict[str, Any]:
    return {
        "request_id": "api-integration-1",
        "agent_type": "assistant",
        "task": "Summarize the deployment knowledge for me.",
        "conversation_history": [
            {"role": "user", "content": "Use the project context."},
        ],
        "memory_query": "deployment",
        "knowledge_query": "deployment",
        "input_metadata": {"source": "api-test"},
    }


def test_agent_run_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/v1/agents/runs", json=_run_payload())

    assert response.status_code == 401


def test_agent_run_orchestrates_context_plan_execution_and_runtime(
    client: TestClient,
) -> None:
    _register(client)
    runtime = SuccessfulRuntime()
    client.app.dependency_overrides[get_agent_runtime] = lambda: runtime

    try:
        create_response = client.post("/api/v1/agents/runs", json=_run_payload())
        assert create_response.status_code == 201, create_response.text
        run = create_response.json()

        assert run["status"] == "succeeded"
        assert run["output_text"] == "Agent run completed by the test runtime."
        assert len(run["steps"]) == 1
        assert run["steps"][0]["status"] == "succeeded"
        assert len(runtime.calls) == 1
        _, runtime_context = runtime.calls[0]
        assert "memory" in runtime_context.input_metadata["context_provider_names"]
        assert "knowledge" in runtime_context.input_metadata["context_provider_names"]
        assert runtime_context.input_metadata["plan_id"]
        assert runtime_context.input_metadata["execution_id"]

        provider_names = run["output_metadata"]["context"]["provider_names"]
        assert set(provider_names) == {
            "conversation_history",
            "runtime_metadata",
            "user_information",
            "agent_configuration",
            "memory",
            "knowledge",
        }
        assert provider_names[:4] == [
            "runtime_metadata",
            "user_information",
            "agent_configuration",
            "conversation_history",
        ]
        event_types = {event["event_type"] for event in run["events"]}
        assert {"context.assembled", "planner.completed", "runtime.completed"} <= event_types
        assert "run.status_changed" in event_types

        run_id = run["id"]
        get_response = client.get(f"/api/v1/agents/runs/{run_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == run_id

        list_response = client.get("/api/v1/agents/runs")
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["id"] == run_id

        events_response = client.get(f"/api/v1/agents/runs/{run_id}/events")
        assert events_response.status_code == 200
        assert events_response.json()["total"] == len(run["events"])
        assert any(
            event["event_type"] == "runtime.completed"
            for event in events_response.json()["items"]
        )

        session_factory = client.app.state.test_session_factory

        async def read_audit_actions() -> set[str]:
            async with session_factory() as session:
                rows = (await session.scalars(select(AuditLog))).all()
                return {row.action for row in rows}

        audit_actions = asyncio.run(read_audit_actions())
        assert {
            "agents.run.requested",
            "agents.run.started",
            "agents.run.succeeded",
        } <= audit_actions
    finally:
        client.app.dependency_overrides.pop(get_agent_runtime, None)


def test_agent_run_isolation_and_cancel_endpoint(client: TestClient) -> None:
    _register(client, email="owner@example.com", full_name="Owner")
    runtime = SuccessfulRuntime()
    client.app.dependency_overrides[get_agent_runtime] = lambda: runtime

    try:
        create_response = client.post(
            "/api/v1/agents/runs",
            json={"agent_type": "assistant", "task": "Keep this run pending."},
        )
        assert create_response.status_code == 201, create_response.text
        run_id = create_response.json()["id"]
    finally:
        client.app.dependency_overrides.pop(get_agent_runtime, None)

    client.post("/api/v1/auth/logout")
    _register(client, email="other@example.com", full_name="Other User")

    isolated_response = client.get(f"/api/v1/agents/runs/{run_id}")
    assert isolated_response.status_code == 404

    client.post("/api/v1/auth/logout")
    _register(client, email="cancel@example.com", full_name="Cancel User")

    session_factory = client.app.state.test_session_factory

    async def create_requested_run() -> uuid.UUID:
        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.email == "cancel@example.com"))
            assert user is not None
            created = await AgentRunService(session).create(
                current_user=user,
                payload=AgentRunCreateRequest(
                    agent_type="assistant",
                    task="Cancel this run before execution.",
                ),
            )
            return created.id

    run_to_cancel = asyncio.run(create_requested_run())
    cancel_response = client.post(f"/api/v1/agents/runs/{run_to_cancel}/cancel")
    assert cancel_response.status_code == 200, cancel_response.text
    assert cancel_response.json()["status"] == "cancelled"
    assert any(
        event["event_type"] == "run.status_changed"
        and event["status"] == "cancelled"
        for event in cancel_response.json()["events"]
    )
