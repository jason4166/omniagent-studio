from __future__ import annotations

import json
import sys
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from omniagent.minimal_graph import MiniState, build_minimal_graph  # noqa: E402


def main() -> None:
    graph = build_minimal_graph()
    print(f"langgraph={version('langgraph')}")
    for message in ("  Hello Day14  ", "   "):
        initial: MiniState = {"message": message, "output_text": ""}
        result = graph.invoke(initial)
        print(json.dumps({"input": initial, "result": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
