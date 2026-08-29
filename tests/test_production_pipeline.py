from pathlib import Path

import pytest

from colonyv_agent import production_agent
from colonyv_agent.tools import pipeline


def test_production_agent_has_execution_and_gate_tools():
    names = {getattr(tool, "__name__", str(tool)) for tool in production_agent.tools}
    assert {"discover_stories", "research_story", "write_script", "direct_visuals",
            "request_render", "publish_to_youtube", "analyze_performance"} <= names
    assert {"evaluate_story_candidate", "evaluate_research_gate", "evaluate_render_result",
            "evaluate_publication_gate", "evaluate_upload_result"} <= names


def test_parse_json_output_extracts_array_after_header():
    text = "log line\n=== Top 2 Stories ===\n[{\"story_id\": \"a\"}, {\"story_id\": \"b\"}]"
    result = pipeline._parse_json_output(text, expect="array")
    assert isinstance(result, list)
    assert len(result) == 2


def test_parse_json_output_rejects_nested_noise():
    text = 'plaintext {\"a\": 1} trailing'
    result = pipeline._parse_json_output(text, expect="object")
    assert result == {"a": 1}


def test_parse_json_output_handles_empty():
    assert pipeline._parse_json_output("") is None
    assert pipeline._parse_json_output("no json here", expect="array") is None


def test_parse_json_output_prefers_outermost_array_with_nested_arrays():
    text = (
        "=== Top 1 Stories ===\n"
        '[{"story_id": "abc", "sources": [{"url": "https://a", "title": "A"}]}]'
    )
    result = pipeline._parse_json_output(text, expect="array")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["story_id"] == "abc"
    assert result[0]["sources"][0]["url"] == "https://a"


def test_parse_json_output_prefers_outermost_object():
    text = "=== Top ===\n{\"claims\": [{\"x\": 1}, {\"x\": 2}], \"summary\": \"s\"}"
    result = pipeline._parse_json_output(text, expect="object")
    assert result == {"claims": [{"x": 1}, {"x": 2}], "summary": "s"}


def test_research_gate_proceeds_with_uncertainty_when_source_was_fetched():
    from colonyv_agent.tools import editorial as ed
    gate = ed.evaluate_research_gate(
        confidence="low", verified_claims=0, total_claims=1,
        contradictions=0, research_attempt=1, sources_fetched=1,
    )
    assert gate["decision"] == "continue"


def test_research_gate_retries_when_no_sources_were_fetched():
    from colonyv_agent.tools import editorial as ed
    gate = ed.evaluate_research_gate(
        confidence="low", verified_claims=0, total_claims=1,
        contradictions=0, research_attempt=1, sources_fetched=0,
    )
    assert gate["decision"] == "retry"


def test_stage_monitor_schedules_research(monkeypatch):
    from colonyv_agent import stages
    state: dict = {"stories_target": 1}

    def fake_discover(tool_context):
        tool_context.state["stories"] = [
            {"index": 0, "story_id": "abc", "title": "T", "relevance_score": 0.9,
             "novelty_score": 0.9, "urgency_score": 0.9}
        ]
        tool_context.state["run_id"] = "r1"
        return {"success": True, "count": 1}

    monkeypatch.setattr(stages, "discover_stories", fake_discover)
    result = stages.run_stage(state, "monitor")
    assert result["decision"] == "continue"
    assert ("research", 0, 1) in result["next"]


def test_stage_research_continue_schedules_script(monkeypatch):
    from colonyv_agent import stages
    state: dict = {"stories_target": 1, "current_story": {"title": "T",
                   "relevance_score": 0.9, "novelty_score": 0.9, "urgency_score": 0.9}}

    def fake_research(idx, tool_context):
        return {"success": True, "confidence": "medium", "verified_claims": 1,
                "total_claims": 1, "contradictions": 0, "sources_fetched": 1,
                "claims": [{"text": "a", "verified": True}]}

    monkeypatch.setattr(stages, "research_story", fake_research)
    result = stages.run_stage(state, "research", 0, 1)
    assert result["decision"] == "continue"
    assert ("script", 0, 1) in result["next"]


def test_stage_research_publishes_unverified_content(monkeypatch):
    from colonyv_agent import stages
    state: dict = {}

    def fake_research(i, tool_context):
        return {"success": True, "confidence": "low", "contradictions": 0,
                "total_claims": 1, "verified_claims": 0, "sources_fetched": 1,
                "claims": [{"text": "a", "verified": False}]}

    monkeypatch.setattr(stages, "research_story", fake_research)
    monkeypatch.setattr(stages, "evaluate_story_candidate", lambda **k: {"decision": "continue"})
    
    result = stages.run_stage(state, "research", 0, 1)
    assert result["decision"] == "continue"
    assert ("script", 0, 1) in result["next"]


def test_stage_research_zero_claims_exhausted_escalates_candidate(monkeypatch):
    from colonyv_agent import stages
    state: dict = {
        "stories": [{"story_id": "1", "title": "a", "index": 0},
                    {"story_id": "2", "title": "b", "index": 1}],
        "stories_target": 2,
    }

    def fake_research(i, tool_context):
        return {"success": True, "confidence": "low", "contradictions": 0,
                "total_claims": 0, "verified_claims": 0, "sources_fetched": 1,
                "claims": []}

    monkeypatch.setattr(stages, "research_story", fake_research)
    monkeypatch.setattr(stages, "evaluate_story_candidate", lambda **k: {"decision": "continue"})
    
    result = stages.run_stage(state, "research", 0, 3)
    assert result["decision"] == "stop"
    assert ("research", 1, 1) in result["next"]


def test_stage_analyst_terminal(monkeypatch):
    from colonyv_agent import stages
    state: dict = {}

    def fake_analyst(tool_context):
        return {"success": True, "analyst": {"topic": "x"}}

    monkeypatch.setattr(stages, "analyze_performance", fake_analyst)
    result = stages.run_stage(state, "analyst", 0, 1)
    assert result["decision"] == "complete"
    assert result["next"] == []


def test_stage_publish_handles_full_report_lists(monkeypatch):
    from colonyv_agent import stages
    state: dict = {
        "research": {
            "confidence": "medium",
            "claims": [{"text": "a", "verified": True}],
            "contradictions": [{"issue": "c1"}],
        }
    }

    def fake_upload(tool_context):
        return {"success": False, "skipped": True, "reason": "skip_publish"}

    monkeypatch.setattr(stages, "publish_to_youtube", fake_upload)
    result = stages.run_stage(state, "publish", 0, 1)
    assert result["decision"] == "skipped"
    assert ("analyst", 0, 1) in result["next"]


def test_python_exec_prefers_venv(tmp_path):
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python3").touch()
    old = Path(".")
    # get_python_exec reads a module-level PROJECT_ROOT; ensure it tolerates missing venv.
    exe = pipeline.get_python_exec()
    assert exe.endswith("python3")


def test_runtime_configure_and_log(monkeypatch):
    from colonyv_agent import pipeline_runtime as rt
    seen = []
    rt.configure(logger=lambda m: seen.append(m), out_dir=Path("/tmp/x"), run="r1", skip=True)
    rt.log("hello")
    assert seen == ["hello"]
    assert rt.run_id == "r1"
    assert rt.skip_publish is True
    rt.configure()
def test_factory_drops_zero_claims_story(monkeypatch):
    from colonyv_agent import factory
    
    def fake_discover(ctx):
        ctx.state["stories"] = [
            {"index": 0, "story_id": "a", "title": "T1", "relevance_score": 0.9, "novelty_score": 0.9, "urgency_score": 0.9}
        ]
        return {"success": True, "count": 1}
    
    def fake_research(idx, ctx):
        return {"success": True, "confidence": "low", "contradictions": 0,
                "total_claims": 0, "verified_claims": 0, "sources_fetched": 1,
                "claims": []}
                
    monkeypatch.setattr(factory, "discover_stories", fake_discover)
    monkeypatch.setattr(factory, "research_story", fake_research)
    
    # We don't need script or render or publish as it should drop before them.
    # But just in case, mock them.
    monkeypatch.setattr(factory, "write_script", lambda ctx: {"success": True})
    monkeypatch.setattr(factory, "direct_visuals", lambda ctx: {"success": True})
    monkeypatch.setattr(factory, "request_render", lambda ctx: {"success": True, "output_exists": True, "output_size_bytes": 200000})
    monkeypatch.setattr(factory, "publish_to_youtube", lambda ctx: {"success": True, "video_id": "abc"})
    monkeypatch.setattr(factory, "analyze_performance", lambda ctx: {"success": True})
    
    # Mock runtime checkpoint to just return True
    monkeypatch.setattr(factory.runtime, "checkpoint", lambda *args: True)
    
    res = factory.run_factory(1)
    
    # It should fail with "No usable candidates were discovered or processed successfully"
    assert "error" in res
    assert res["error"] == "No usable candidates were discovered or processed successfully"



def test_factory_publication_gate_uses_full_report_from_state(monkeypatch):
    """Regression: the research tool returns counts (int contradictions, no claims
    key); the publication gate must read the full report from ctx.state, else
    'object of type int has no len()' crashes the run."""
    from colonyv_agent import factory

    def fake_discover(ctx):
        ctx.state["stories"] = [
            {"index": 0, "story_id": "a", "title": "T1", "relevance_score": 0.9, "novelty_score": 0.9, "urgency_score": 0.9}
        ]
        return {"success": True, "count": 1}

    calls = {"research": 0}

    def fake_research(idx, ctx):
        calls["research"] += 1
        # Matches the real research_story() tool return: counts only, no claims.
        ctx.state["research"] = {
            "claims": [{"text": "c1", "verified": False}, {"text": "c2", "verified": False}],
            "contradictions": [],
            "confidence": "low",
            "sources": [{"url": "https://x"}],
        }
        return {"success": True, "confidence": "low", "verified_claims": 0,
                "total_claims": 2, "contradictions": 0, "sources_fetched": 1}

    monkeypatch.setattr(factory, "discover_stories", fake_discover)
    monkeypatch.setattr(factory, "research_story", fake_research)
    monkeypatch.setattr(factory, "write_script", lambda ctx: {"success": True})
    monkeypatch.setattr(factory, "direct_visuals", lambda ctx: {"success": True, "shots": 4, "distinct_layouts": 3, "illustrations_planned": 3, "accent_role": "topic"})
    monkeypatch.setattr(factory, "request_render", lambda ctx: {"success": True, "output_exists": True, "output_size_bytes": 200000})
    monkeypatch.setattr(factory, "publish_to_youtube", lambda ctx: {"success": True, "video_id": "abc"})
    monkeypatch.setattr(factory, "analyze_performance", lambda ctx: {"success": True})
    monkeypatch.setattr(factory.runtime, "checkpoint", lambda *args: True)

    res = factory.run_factory(1)

    assert "error" not in res
    assert len(res["stories_produced"]) == 1
    assert calls["research"] == 1
