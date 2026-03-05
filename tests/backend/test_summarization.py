import pytest
from backend.services.summarization_service import SummarizationService

def test_summarize_empty_text():
    svc = SummarizationService()
    assert svc.summarize("") == ""
    assert svc.summarize(None) == ""

def test_summarize_short_text():
    svc = SummarizationService()
    text = "This is a short sentence."
    # Should return text as-is if below max_sentences
    assert svc.summarize(text) == text

def test_word_count():
    svc = SummarizationService()
    assert svc.word_count("Hello world") == 2
    assert svc.word_count("") == 0
