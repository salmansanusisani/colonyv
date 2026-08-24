"""Basic tests for the stdout JSON parser used by dashboard and pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.app import parse_json_from_output


def test_parse_array_after_header():
    output = "[1/3] Fetching feeds...\n  Fetched 50 entries\n  20 new stories\n[2/3] Scoring...\n[3/3] Validating...\n=== Top 5 Stories ===\n[{\"title\": \"Test\", \"url\": \"https://example.com\"}]"
    result = parse_json_from_output(output, "array")
    assert result is not None
    assert len(result) == 1
    assert result[0]["title"] == "Test"


def test_parse_array_no_header():
    output = "some log line\n[1/2] Stuff\n[{\"a\": 1}]"
    result = parse_json_from_output(output, "array")
    assert result is not None
    assert result[0]["a"] == 1


def test_parse_object():
    output = "Researching...\n{\"claims\": [{\"text\": \"x\"}], \"confidence\": \"high\"}"
    result = parse_json_from_output(output, "object")
    assert result is not None
    assert result["confidence"] == "high"
    assert len(result["claims"]) == 1


def test_parse_empty_output():
    result = parse_json_from_output("", "array")
    assert result is None


def test_parse_no_json():
    result = parse_json_from_output("just plain text\nno json here", "array")
    assert result is None


def test_parse_string_with_brackets():
    output = "=== Top 2 Stories ===\n[{\"title\": \"Breaking: [Crypto] surges\", \"url\": \"https://example.com\"}]"
    result = parse_json_from_output(output, "array")
    assert result is not None
    assert len(result) == 1


def test_parse_multiline_json():
    output = "Done.\n=== Top 1 Stories ===\n[\n  {\n    \"title\": \"AI News\",\n    \"url\": \"https://example.com\"\n  }\n]"
    result = parse_json_from_output(output, "array")
    assert result is not None
    assert result[0]["title"] == "AI News"


if __name__ == "__main__":
    for name, func in list(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                print(f"  PASS: {name}")
            except Exception as e:
                print(f"  FAIL: {name} - {e}")
    print("Done.")
