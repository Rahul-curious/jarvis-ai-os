from langgraph.graph import StateGraph

from jarvis_agents.state import AgentRunState


def create_agent_graph() -> StateGraph:
    """Create the Phase 1 LangGraph builder without business nodes."""
    return StateGraph(AgentRunState)
