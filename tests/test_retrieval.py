from omniagent.retrieval import FakeRetriever, Retriever


def test_fake_retriever_returns_configured_response_and_records_request() -> None:
    fake_retriever = FakeRetriever(
        response="Synthetic knowledge: remote support is available from 09:00 to 18:00."
    )
    retriever: Retriever = fake_retriever

    result = retriever.retrieve(
        knowledge_base_ids=["general-kb-v1"],
        query="What are the synthetic remote-support hours?",
    )

    assert result == "Synthetic knowledge: remote support is available from 09:00 to 18:00."
    assert fake_retriever.requests == [
        (
            ("general-kb-v1",),
            "What are the synthetic remote-support hours?",
        )
    ]
