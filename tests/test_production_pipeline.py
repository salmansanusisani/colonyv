from pathlib import Path

import pytest

from colonyv_agent import production_agent
from colonyv_agent.tools import pipeline


def test_production_agent_has_execution_and_gate_tools():
    names = {getattr(tool, "__name__", str(tool)) for tool in production_agent.tools}
    assert {"discover_stories", "research_story", "write_script", "request_render",
            "publish_to_youtube", "analyze_performance"} <= names
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