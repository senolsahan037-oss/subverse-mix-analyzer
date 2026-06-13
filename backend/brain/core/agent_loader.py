from pathlib import Path
import yaml

AGENTS_DIR = Path("brain/agents")

def load_agents():
    agents = {}

    for file in AGENTS_DIR.glob("*.yaml"):
        with open(file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        name = data["agent"]["name"]
        agents[name] = data

    return agents
