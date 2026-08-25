from typing import Protocol

from omniagent.profiles import AgentProfile


class AgentProfileRepository(Protocol):
    def get(self, profile_id: str) -> AgentProfile | None: ...

    def save(self, profile: AgentProfile) -> None: ...

    def list_all(self) -> list[AgentProfile]: ...


class InMemoryAgentProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}

    def get(self, profile_id: str) -> AgentProfile | None:
        return self._profiles.get(profile_id)

    def save(self, profile: AgentProfile) -> None:
        self._profiles[profile.profile_id] = profile

    def list_all(self) -> list[AgentProfile]:
        return list(self._profiles.values())
