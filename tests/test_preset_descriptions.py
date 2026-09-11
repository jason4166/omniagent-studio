import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from omniagent.database import build_engine
from omniagent.db_models import KnowledgeBaseRow
from omniagent.postgres_repositories import SqlAlchemyAgentProfileRepository
from omniagent.presets import refresh_preset_presentation, seed
from omniagent.profiles import AgentProfile
from omniagent.session_store import SessionStore

pytestmark = pytest.mark.integration


@pytest.fixture
def description_store() -> Iterator[SessionStore]:
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    engine = build_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            store = SessionStore(engine)
            store.factory = sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                yield store
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def isolated_preset(directory: Path, identifier: str) -> tuple[AgentProfile, str]:
    configuration = json.loads(Path("presets/profiles.json").read_text(encoding="utf-8"))
    entry = next(row for row in configuration if row["profile"]["profile_id"] == identifier)
    profile = AgentProfile.model_validate(entry["profile"]).model_copy(
        update={
            "profile_id": "description-" + uuid4().hex,
            "prompt_version_id": "description-" + uuid4().hex,
            "tool_ids": [],
            "knowledge_base_ids": [],
        }
    )
    entry["profile"] = profile.model_dump(mode="json")
    (directory / "profiles.json").write_text(json.dumps([entry]), encoding="utf-8")
    return profile, str(entry["previous_description"])


@pytest.mark.parametrize("identifier", ["hr", "support", "sales"])
def test_description_refresh_is_exact_idempotent_and_preserves_configuration(
    description_store: SessionStore, tmp_path: Path, identifier: str
) -> None:
    profile, previous = isolated_preset(tmp_path, identifier)
    assert refresh_preset_presentation(description_store, tmp_path)["updated_descriptions"] == 0
    assert seed(description_store, [], tmp_path)["created_profiles"] == 1
    with description_store.factory.begin() as db:
        repository = SqlAlchemyAgentProfileRepository(db)
        installed = repository.get(profile.profile_id)
        assert installed is not None
        assert installed.description == profile.description
        installed.description = previous
        installed.version = 9
        installed.enabled = False
        installed.allowed_roles = ("admin",)
        installed.auto_approve_read = False
        installed.require_evidence = True
        installed.budgets = installed.budgets.model_copy(update={"max_steps": 12})
        repository.save(installed)
        expected = installed.model_dump(mode="json") | {"description": profile.description}

    assert seed(description_store, [], tmp_path)["updated_descriptions"] == 1
    assert seed(description_store, [], tmp_path)["updated_descriptions"] == 0
    with description_store.factory.begin() as db:
        repository = SqlAlchemyAgentProfileRepository(db)
        actual = repository.get(profile.profile_id)
        assert actual is not None and actual.model_dump(mode="json") == expected
        actual.description = previous
        repository.save(actual)

    assert refresh_preset_presentation(description_store, tmp_path)["updated_descriptions"] == 1
    assert refresh_preset_presentation(description_store, tmp_path)["updated_descriptions"] == 0
    with description_store.factory() as db:
        actual = SqlAlchemyAgentProfileRepository(db).get(profile.profile_id)
        assert actual is not None and actual.model_dump(mode="json") == expected


@pytest.mark.parametrize("customization", ["custom", "trailing-space"])
def test_description_refresh_preserves_customized_text(
    description_store: SessionStore, tmp_path: Path, customization: str
) -> None:
    profile, previous = isolated_preset(tmp_path, "hr")
    seed(description_store, [], tmp_path)
    customized = "团队自己维护的制度查询入口" if customization == "custom" else previous + " "
    with description_store.factory.begin() as db:
        repository = SqlAlchemyAgentProfileRepository(db)
        installed = repository.get(profile.profile_id)
        assert installed is not None
        installed.description = customized
        repository.save(installed)

    assert refresh_preset_presentation(description_store, tmp_path)["updated_descriptions"] == 0
    assert seed(description_store, [], tmp_path)["updated_descriptions"] == 0
    with description_store.factory() as db:
        actual = SqlAlchemyAgentProfileRepository(db).get(profile.profile_id)
        assert actual is not None and actual.description == customized


@pytest.mark.parametrize("customized", [False, True])
def test_knowledge_label_refresh_preserves_identity_creation_time_and_custom_names(
    description_store: SessionStore, tmp_path: Path, customized: bool
) -> None:
    isolated_preset(tmp_path, "hr")
    configuration = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    identifier = "description-kb-" + uuid4().hex
    configuration[0]["profile"]["knowledge_base_ids"] = [identifier]
    (tmp_path / "profiles.json").write_text(json.dumps(configuration), encoding="utf-8")
    original = "团队制度资料" if customized else configuration[0]["previous_knowledge_name"]
    created_at = datetime(2026, 9, 10, tzinfo=UTC)
    with description_store.factory.begin() as db:
        db.add(KnowledgeBaseRow(knowledge_base_id=identifier, name=original, created_at=created_at))

    result = refresh_preset_presentation(description_store, tmp_path)
    assert result["updated_knowledge_names"] == (0 if customized else 1)
    assert refresh_preset_presentation(description_store, tmp_path)["updated_knowledge_names"] == 0
    with description_store.factory() as db:
        row = db.get(KnowledgeBaseRow, identifier)
        assert row is not None and row.created_at == created_at
        assert row.name == (original if customized else "员工制度")
