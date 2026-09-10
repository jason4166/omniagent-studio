"""Day14 isolated two-node graph; not the production AgentRuntime."""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph


class MiniState(TypedDict):
    message: str
    output_text: str


def normalize_message(state: MiniState) -> dict[str, str]:
    return {"message": state["message"].strip()}


def respond(state: MiniState) -> dict[str, str]:
    return {"output_text": f"Received: {state['message']}"}


def route_message(state: MiniState) -> Literal["respond", "stop"]:
    if state["message"]:
        return "respond"
    return "stop"


def build_minimal_graph() -> CompiledStateGraph[MiniState, None, MiniState, MiniState]:
    builder = StateGraph(MiniState)
    builder.add_node("normalize_message", normalize_message)
    builder.add_node("respond", respond)
    builder.add_edge(START, "normalize_message")
    builder.add_conditional_edges(
        "normalize_message", route_message, {"respond": "respond", "stop": END}
    )
    builder.add_edge("respond", END)
    return builder.compile().with_config({"recursion_limit": 3})
