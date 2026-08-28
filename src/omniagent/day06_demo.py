from pydantic import BaseModel


class OfflineMessage(BaseModel):
    role: str
    content: str


class OfflineRequest(BaseModel):
    model: str
    messages: list[OfflineMessage]


class OfflineResponse(BaseModel):
    model: str
    content: str


def offline_generate(request: OfflineRequest) -> OfflineResponse:
    return OfflineResponse(
        model=request.model,
        content="billing",
    )


request = OfflineRequest(
    model="local-fake",
    messages=[
        OfflineMessage(
            role="system",
            content="Classify the request.",
        ),
        OfflineMessage(
            role="user",
            content="Refund order",
        ),
        OfflineMessage(
            role="tool",
            content="Order status: paid",
        ),
    ],
)
response = offline_generate(request)

print(request.model_dump())
print(response.model_dump())
