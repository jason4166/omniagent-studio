from typing import Protocol


class Retriever(Protocol):
    def retrieve(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> str: ...


class FakeRetriever:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[tuple[tuple[str, ...], str]] = []

    def retrieve(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> str:
        self.requests.append((tuple(knowledge_base_ids), query))
        return self.response
