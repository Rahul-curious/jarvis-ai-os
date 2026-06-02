from jarvis_agents import AgentRunState


def test_agent_state_accepts_phase_one_identifiers() -> None:
    state: AgentRunState = {
        "tenant_id": "tenant_001",
        "workspace_id": "workspace_001",
        "status": "scaffolded",
    }

    assert state["status"] == "scaffolded"
