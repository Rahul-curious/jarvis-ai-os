from typing import TypedDict


class AgentRunState(TypedDict, total=False):
    """Shared state shape reserved for future LangGraph agent runs."""

    tenant_id: str
    workspace_id: str
    user_id: str
    task_id: str
    request_id: str
    status: str
