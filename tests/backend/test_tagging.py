import pytest
from backend.services.tagging_service import TaggingService

def test_extract_tags():
    svc = TaggingService()
    # Test keyword matching
    tags = svc.extract_tags("Cricket match in Chennai", "The player scored a century.")
    tag_names = [t[0] for t in tags]
    assert "Sports" in tag_names
    
    # Test slugification
    assert tags[0][1] == "sports"

def test_extract_tags_no_match():
    svc = TaggingService()
    tags = svc.extract_tags("Unknown content here", "Nothing to see.")
    assert len(tags) == 0
