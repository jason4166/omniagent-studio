from omniagent.day06_demo import (
    OfflineMessage,
    OfflineRequest,
    OfflineResponse,
    offline_generate,
)


def test_offline_generate_returns_typed_response() -> None:
    request = OfflineRequest(
        model="local-fake",
        messages=[
            OfflineMessage(
                role="user",
                content="Refund order",
            )
        ],
    )

    response = offline_generate(request)

    assert response == OfflineResponse(
        model="local-fake",
        content="billing",
    )
