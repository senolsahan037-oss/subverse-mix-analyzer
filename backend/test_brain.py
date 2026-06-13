from brain.core.registry import AgentRegistry
from brain.core.dispatcher import BrainDispatcher

registry = AgentRegistry()

print("Agents:")
print(registry.list_agents())

dispatcher = BrainDispatcher()

agent = dispatcher.route(
    "Subverse Lab için dashboard ve landing page oluştur"
)

print("\nSelected:")
print(agent["agent"]["name"])
