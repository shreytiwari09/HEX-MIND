import os


def test_langsmith_tracing_is_off() -> None:
    """LangChain must never send traces to LangSmith: nothing leaves the machine."""
    import app.config  # noqa: F401  (importing the settings module sets the defaults)

    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
