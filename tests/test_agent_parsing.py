"""Agent response parsing tests, against real agents/base.py.

The test loads agents/base.py from the repo root (see conftest).
If that file cannot be found, every test here is skipped with a
clear reason instead of testing a copy.

The agent object is built with object.__new__ on purpose:
BaseAgent.__init__ would import the LLM client (and, with an API
key, the google-genai SDK), which these parsing tests do not
need. _parse_response only needs the agent_name property, so
bypassing __init__ keeps the tests stdlib-only and offline.

Parsing behaviour in agents/base.py as read:

* A JSON array becomes a list of CodeIssue objects.
* Markdown fences and surrounding text are stripped.
* A non-list JSON value, or invalid JSON, yields an empty list.
* A malformed item (for example an unknown severity) is skipped,
  not fatal.
* Missing title defaults to "Issue found", missing line_start
  defaults to 1, missing line_end stays None.
* category is set to the agent name.
"""

import pytest

from conftest import find_repo_file, load_module_from_path


def _load_base():
    path = find_repo_file("agents/base.py")
    if path is None:
        pytest.skip(
            "agents/base.py not found; run pytest from the repo root "
            "or set PRPILOT_REPO_ROOT"
        )
    return load_module_from_path("prpilot_agents_base", path)


def _make_agent(module):
    class SecurityAgent(module.BaseAgent):
        @property
        def agent_name(self):
            return "security"

        @property
        def system_prompt(self):
            return "test prompt"

    agent = object.__new__(SecurityAgent)
    return agent


def _parse(text):
    module = _load_base()
    agent = _make_agent(module)
    return agent._parse_response(text, "src/app.py"), module


def test_plain_json_array():
    issues, module = _parse(
        '[{"line_start": 10, "line_end": 12, "severity": "high", '
        '"title": "SQL injection", "description": "User input in query", '
        '"suggestion": "Use parameters", "code_snippet": "query = f..."}]'
    )
    assert len(issues) == 1
    issue = issues[0]
    assert isinstance(issue, module.CodeIssue)
    assert issue.file_path == "src/app.py"
    assert issue.line_start == 10
    assert issue.line_end == 12
    assert issue.severity == module.IssueSeverity.HIGH
    assert issue.category == "security"
    assert issue.title == "SQL injection"
    assert issue.suggestion == "Use parameters"


def test_fenced_json_and_surrounding_text():
    import json

    data = [
        {
            "line_start": 3,
            "severity": "low",
            "title": "Naming",
            "description": "Unclear name",
        }
    ]
    text = chr(10).join(["Here is the review:", "```json", json.dumps(data), "```", "Done."])
    issues, _ = _parse(text)
    assert len(issues) == 1
    assert issues[0].line_start == 3
    assert issues[0].severity.value == "low"
    assert issues[0].line_end is None


def test_empty_array_and_defaults():
    issues, _ = _parse("[]")
    assert issues == []
    issues, _ = _parse('[{"line_start": 5, "severity": "info"}]')
    assert len(issues) == 1
    assert issues[0].title == "Issue found"
    assert issues[0].description == ""
    assert issues[0].suggestion is None


def test_invalid_json_returns_empty():
    issues, _ = _parse("this is not json at all")
    assert issues == []


def test_non_list_json_returns_empty():
    issues, _ = _parse('{"line_start": 1, "severity": "high"}')
    assert issues == []


def test_malformed_issue_is_skipped_not_fatal():
    issues, _ = _parse(
        '[{"line_start": 1, "severity": "not-a-severity", "title": "Bad"}, '
        '{"line_start": 2, "severity": "medium", "title": "Good", '
        '"description": "Real issue"}]'
    )
    assert len(issues) == 1
    assert issues[0].title == "Good"


def test_file_review_dataclass_shape():
    module = _load_base()
    review = module.FileReview(
        file_path="src/app.py", issues=[], summary="No issues"
    )
    assert review.file_path == "src/app.py"
    assert review.issues == []
    assert review.summary == "No issues"
    assert set(module.IssueSeverity) == {
        module.IssueSeverity.CRITICAL,
        module.IssueSeverity.HIGH,
        module.IssueSeverity.MEDIUM,
        module.IssueSeverity.LOW,
        module.IssueSeverity.INFO,
    }
