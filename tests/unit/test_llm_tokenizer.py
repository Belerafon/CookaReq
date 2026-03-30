from app.llm import tokenizer


def test_count_text_tokens_falls_back_when_tiktoken_encoding_download_fails(
    monkeypatch,
):
    class BrokenTiktokenModule:
        @staticmethod
        def get_encoding(_name: str):
            raise RuntimeError("network unavailable")

    monkeypatch.setattr(tokenizer, "_load_tiktoken", lambda: BrokenTiktokenModule())

    result = tokenizer.count_text_tokens("one two three")

    assert result.tokens == 3
    assert result.approximate is True
    assert result.reason == "fallback_whitespace"
