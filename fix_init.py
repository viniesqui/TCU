import glob

for path in glob.glob("src/agents/*.py"):
    if "base_agent.py" in path or "orchestrator.py" in path or "__init__.py" in path:
        continue
    with open(path, "r") as f:
        content = f.read()
    
    content = content.replace("def __init__(self) -> None:", "def __init__(self, max_cost: float | None = None) -> None:")
    content = content.replace("super().__init__(", "super().__init__(max_cost=max_cost, ")
    
    with open(path, "w") as f:
        f.write(content)
print("Updated all agent files")
