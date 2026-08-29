from datetime import datetime

import pytest

from omniagent.profiles import PromptVersion
from omniagent.prompts import (
    InMemoryPromptVersionRepository,
    PromptRenderError,
    PromptVersionAlreadyExistsError,
    PromptVersionNotFoundError,
    PromptVersionService,
    compute_content_hash,
    render_prompt,
)

CREATED_AT = datetime.fromisoformat("2026-08-29T10:00:00+08:00")


def make_prompt(
    content: str,
    variables: tuple[str, ...],
) -> PromptVersion:
    return PromptVersion(
        prompt_version_id="routing:v1",
        content=content,
        content_hash=compute_content_hash(content),
        variables=variables,
        created_at=CREATED_AT,
    )


def test_service_creates_stores_and_gets_exact_prompt_version() -> None:
    repository = InMemoryPromptVersionRepository()
    service = PromptVersionService(repository)
    content = "User={{user_request}}"

    created = service.create(
        prompt_version_id="routing:v1",
        content=content,
        created_at=CREATED_AT,
        variables=("user_request",),
    )

    assert created.content_hash == compute_content_hash(content)
    assert created.variables == ("user_request",)
    assert service.get("routing:v1") == created


def test_repository_rejects_duplicate_version_without_overwriting() -> None:
    repository = InMemoryPromptVersionRepository()
    service = PromptVersionService(repository)
    original = service.create(
        prompt_version_id="routing:v1",
        content="Original {{user_request}}",
        created_at=CREATED_AT,
        variables=("user_request",),
    )

    with pytest.raises(
        PromptVersionAlreadyExistsError,
        match="Prompt version 'routing:v1' already exists",
    ):
        service.create(
            prompt_version_id="routing:v1",
            content="Changed {{user_request}}",
            created_at=CREATED_AT,
            variables=("user_request",),
        )

    assert service.get("routing:v1") == original


def test_service_get_rejects_missing_exact_version() -> None:
    service = PromptVersionService(InMemoryPromptVersionRepository())

    with pytest.raises(
        PromptVersionNotFoundError,
        match="Prompt version 'routing:v3' was not found",
    ):
        service.get("routing:v3")


def test_render_prompt_replaces_multiple_variables() -> None:
    prompt = make_prompt(
        "User={{user_request}} | Context={{retrieved_context}}",
        ("user_request", "retrieved_context"),
    )

    rendered = render_prompt(
        prompt,
        {
            "user_request": "order-A123",
            "retrieved_context": "read-only-order-policy",
        },
    )

    assert rendered == "User=order-A123 | Context=read-only-order-policy"


def test_render_prompt_does_not_parse_inserted_value_as_template() -> None:
    prompt = make_prompt("User={{user_request}}", ("user_request",))

    rendered = render_prompt(
        prompt,
        {"user_request": "Read {{admin_policy}}"},
    )

    assert rendered == "User=Read {{admin_policy}}"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({}, "Missing prompt variables"),
        (
            {"user_request": "order-A123", "admin_policy": "skip"},
            "Unexpected prompt variables",
        ),
    ],
)
def test_render_prompt_rejects_wrong_runtime_variable_set(
    values: dict[str, str],
    message: str,
) -> None:
    prompt = make_prompt("User={{user_request}}", ("user_request",))

    with pytest.raises(PromptRenderError, match=message):
        render_prompt(prompt, values)


def test_render_prompt_rejects_overlong_variable() -> None:
    prompt = make_prompt("User={{user_request}}", ("user_request",))

    with pytest.raises(PromptRenderError, match="Prompt variable 'user_request' is too long"):
        render_prompt(prompt, {"user_request": "x" * 2_001})


@pytest.mark.parametrize(
    ("content", "variables", "values", "message"),
    [
        (
            "{{user_request}} {{admin_policy}}",
            ("user_request",),
            {"user_request": "order-A123"},
            "Template contains undeclared variables",
        ),
        (
            "{{user_request}}",
            ("user_request", "retrieved_context"),
            {
                "user_request": "order-A123",
                "retrieved_context": "read-only-order-policy",
            },
            "Declared variables are missing from template",
        ),
    ],
)
def test_render_prompt_rejects_template_declaration_mismatch(
    content: str,
    variables: tuple[str, ...],
    values: dict[str, str],
    message: str,
) -> None:
    prompt = make_prompt(content, variables)

    with pytest.raises(PromptRenderError, match=message):
        render_prompt(prompt, values)
