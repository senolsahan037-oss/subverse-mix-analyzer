from .agent_loader import load_agents

class AgentRegistry:
    def __init__(self):
        self.agents = load_agents()

    def list_agents(self):
        return list(self.agents.keys())

    def get(self, name):
        return self.agents.get(name)
