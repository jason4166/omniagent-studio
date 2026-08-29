import hashlib
import re
from datetime import datetime
from typing import Protocol

from omniagent.profiles import PromptVersion

MAX_PROMPT_VARIABLE_LENGTH = 2_000
PROMPT_VARIABLE_PATTERN = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class PromptVersionAlreadyExistsError(RuntimeError):
    pass


class PromptVersionNotFoundError(RuntimeError):
    pass


class PromptRenderError(ValueError):
    pass


def render_prompt(
    prompt: PromptVersion,
    values: dict[str, str],
) -> str:
    declared_variables = set(prompt.variables)
    provided_variables = set(values)

    missing_variables = declared_variables - provided_variables
    if missing_variables:
        raise PromptRenderError("Missing prompt variables")

    unexpected_variables = provided_variables - declared_variables
    if unexpected_variables:
        raise PromptRenderError("Unexpected prompt variables")

    for variable_name, value in values.items():
        if len(value) > MAX_PROMPT_VARIABLE_LENGTH:
            raise PromptRenderError(f"Prompt variable '{variable_name}' is too long")

    template_variables = set(PROMPT_VARIABLE_PATTERN.findall(prompt.content))

    undeclared_variables = template_variables - declared_variables
    if undeclared_variables:
        raise PromptRenderError("Template contains undeclared variables")

    unused_variables = declared_variables - template_variables
    if unused_variables:
        raise PromptRenderError("Declared variables are missing from template")

    def replace_variable(
        match: re.Match[str],
    ) -> str:
        variable_name = match.group(1)
        return values[variable_name]

    return PROMPT_VARIABLE_PATTERN.sub(
        replace_variable,
        prompt.content,
    )


class InMemoryPromptVersionRepository:
    def __init__(self) -> None:
        self._prompts: dict[str, PromptVersion] = {}

    def get(self, prompt_version_id: str) -> PromptVersion | None:
        return self._prompts.get(prompt_version_id)

    def save(self, prompt: PromptVersion) -> None:
        if prompt.prompt_version_id in self._prompts:
            raise PromptVersionAlreadyExistsError(
                f"Prompt version '{prompt.prompt_version_id}' already exists"
            )

        self._prompts[prompt.prompt_version_id] = prompt


class PromptVersionRepository(Protocol):
    def get(self, prompt_version_id: str) -> PromptVersion | None: ...
    def save(self, prompt: PromptVersion) -> None: ...


class PromptVersionService:
    def __init__(self, repository: PromptVersionRepository) -> None:
        self._repository = repository

    def create(
        self,
        prompt_version_id: str,
        content: str,
        created_at: datetime,
        variables: tuple[str, ...] = (),
    ) -> PromptVersion:
        prompt = PromptVersion(
            prompt_version_id=prompt_version_id,
            content=content,
            content_hash=compute_content_hash(content),
            created_at=created_at,
            variables=variables,
        )

        self._repository.save(prompt)
        return prompt

    def get(self, prompt_version_id: str) -> PromptVersion:
        prompt = self._repository.get(prompt_version_id)

        if prompt is None:
            raise PromptVersionNotFoundError(f"Prompt version '{prompt_version_id}' was not found")

        return prompt
