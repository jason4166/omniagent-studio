import json

import pytest

from omniagent.minimal_graph import MiniState, build_minimal_graph, normalize_message


def test_normalize_message_returns_partial_update_without_mutating_input() -> None:
    initial: MiniState = {"message": "  hello  ", "output_text": "unchanged"}

    assert normalize_message(initial) == {"message": "hello"}
    assert initial == {"message": "  hello  ", "output_text": "unchanged"}


@pytest.mark.parametrize(
    ("message", "expected", "expected_nodes"),
    [
        ("  hello  ", "Received: hello", ["normalize_message", "respond"]),
        (" \t\n ", "", ["normalize_message"]),
    ],
)
def test_minimal_graph_routes_and_preserves_serializable_state(
    message: str, expected: str, expected_nodes: list[str]
) -> None:
    graph = build_minimal_graph()
    initial: MiniState = {"message": message, "output_text": ""}

    result = graph.invoke(initial)
    updates = list(graph.stream(initial, stream_mode="updates"))

    assert result == {"message": message.strip(), "output_text": expected}
    assert json.loads(json.dumps(result)) == result
    assert [node for update in updates for node in update] == expected_nodes
    assert initial == {"message": message, "output_text": ""}
