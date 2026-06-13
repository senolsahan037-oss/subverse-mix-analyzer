from brain.core.registry import AgentRegistry

class BrainDispatcher:
    def __init__(self):
        self.registry = AgentRegistry()

    def route(self, task: str):
        task = task.lower()

        if any(word in task for word in [
            "web", "ui", "dashboard", "landing",
            "frontend", "site", "design", "tasarım"
        ]):
            return self.registry.get("AI-WebDesigner")

        return None
