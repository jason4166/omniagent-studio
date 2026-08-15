from omniagent.smoke import project_smoke


def test_project_smoke() -> None:
    assert project_smoke() == "omniagent-studio:ok"
