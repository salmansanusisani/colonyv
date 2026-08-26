from colonyv_agent.tools.editorial import (
    evaluate_publication_gate,
    evaluate_render_result,
    evaluate_research_gate,
    evaluate_story_candidate,
    evaluate_upload_result,
)


def test_unimportant_story_stops():
    result = evaluate_story_candidate("Routine update", 0.4, 0.3, 0.2)
    assert result["decision"] == "stop"


def test_important_story_continues():
    result = evaluate_story_candidate("Major model launch", 0.95, 0.8, 0.9)
    assert result["decision"] == "continue"


def test_weak_research_retries_then_stops():
    retry = evaluate_research_gate("low", 1, 5, 2, research_attempt=1)
    stop = evaluate_research_gate("low", 1, 5, 2, research_attempt=3)
    assert retry["decision"] == "retry"
    assert stop["decision"] == "stop"


def test_medium_confidence_requires_approval():
    review = evaluate_publication_gate("medium", 0, 0, False)
    publish = evaluate_publication_gate("medium", 0, 0, True)
    assert review["decision"] == "review"
    assert publish["decision"] == "publish"


def test_unsupported_claim_blocks_publication():
    result = evaluate_publication_gate("high", 0, 1, True)
    assert result["decision"] == "block"


def test_render_and_upload_retry_policies():
    assert evaluate_render_result(False, False, 0, 1)["decision"] == "retry"
    assert evaluate_render_result(False, False, 0, 2)["decision"] == "stop"
    assert evaluate_upload_result(False, "", 1)["decision"] == "retry"
    assert evaluate_upload_result(True, "abc123", 1)["decision"] == "complete"
