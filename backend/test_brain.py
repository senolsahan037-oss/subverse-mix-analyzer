from backend.brain.core.registry import AgentRegistry
from backend.brain.core.dispatcher import BrainDispatcher

def test_registry_loads_configured_agent() -> None:
    registry = AgentRegistry()
    assert registry.list_agents() == ["AI-WebDesigner"]


def test_dispatcher_routes_dashboard_request() -> None:
    dispatcher = BrainDispatcher()
    agent = dispatcher.route("Subverse Lab için dashboard ve landing page oluştur")

    assert agent is not None
    assert agent["agent"]["name"] == "AI-WebDesigner"
