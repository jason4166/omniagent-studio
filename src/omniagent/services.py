from omniagent.profiles import AgentProfile, AgentProfilePatch
from omniagent.repositories import AgentProfileRepository


class AgentProfileAlreadyExistsError(RuntimeError):
    pass


class AgentProfileNotFoundError(RuntimeError):
    pass


class AgentProfileVersionConflictError(RuntimeError):
    pass


class AgentProfileService:
    def __init__(self, repository: AgentProfileRepository) -> None:
        self._repository = repository

    def create(self, profile: AgentProfile) -> AgentProfile:
        existing = self._repository.get(profile.profile_id)
        if existing is not None:
            raise AgentProfileAlreadyExistsError(
                f"Agent profile '{profile.profile_id}' already exists"
            )

        self._repository.save(profile)
        return profile

    def get(self, profile_id: str) -> AgentProfile:
        profile = self._repository.get(profile_id)

        if profile is None:
            raise AgentProfileNotFoundError(f"Agent profile '{profile_id}' was not found")

        return profile

    def update(
        self,
        profile_id: str,
        patch: AgentProfilePatch,
    ) -> AgentProfile:
        current = self.get(profile_id)

        if current.version != patch.expected_version:
            raise AgentProfileVersionConflictError(
                f"Agent profile '{profile_id}' version conflict: "
                f"expected {patch.expected_version}, current {current.version}"
            )

        updates = patch.model_dump(
            exclude_unset=True,
            exclude={"expected_version"},
        )

        candidate = current.model_dump()
        candidate.update(updates)
        candidate["version"] = current.version + 1

        updated = AgentProfile.model_validate(candidate)

        self._repository.save(updated)
        return updated
