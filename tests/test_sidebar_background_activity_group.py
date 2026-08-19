"""Regression coverage for the collapsed background-activity session group."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SESSIONS_JS = ROOT / "static" / "sessions.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node(source: str) -> str:
    result = subprocess.run(
        [NODE],
        input=source,
        cwd=str(ROOT),
        capture_output=True,
        encoding="utf-8",
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract {name}")


def test_background_activity_classifier_uses_source_not_title():
    source = SESSIONS_JS.read_text(encoding="utf-8")
    helper = _extract_function(source, "_isBackgroundSidebarSession")
    script = f"""
{helper}
const rows = [
  {{session_source: 'kanban', title: 'Kanban Session'}},
  {{raw_source: 'tool', title: 'Tool Session'}},
  {{session_source: 'webui', title: 'Kanban Session'}},
  {{session_source: 'webui', raw_source: 'tool', title: 'Normal WebUI chat'}},
  {{session_source: 'cli', title: 'Tool Session'}},
  {{session_source: 'webui', title: 'Normal chat'}},
];
console.log(JSON.stringify(rows.map(_isBackgroundSidebarSession)));
"""
    result = json.loads(_run_node(script))
    assert result == [True, True, False, False, False, False]


def test_background_activity_is_grouped_after_regular_conversations():
    source = SESSIONS_JS.read_text(encoding="utf-8")
    classifier = _extract_function(source, "_isBackgroundSidebarSession")
    builder = _extract_function(source, "_buildSidebarSessionGroups")
    collapse = _extract_function(source, "_isSidebarGroupCollapsed")
    script = f"""
const BACKGROUND_ACTIVITY_GROUP_KEY = '__background_activity__';
function t(key, count) {{ return key === 'session_background_activity' ? `Background activity (${{count}})` : key; }}
function _sessionSortTimestampMs(row) {{ return row.updated_at; }}
function _sessionTimeBucketLabel(timestamp) {{ return timestamp >= 100 ? 'Today' : 'Older'; }}
{classifier}
{builder}
{collapse}
const rows = [
  {{session_id: 'tool-1', session_source: 'tool', updated_at: 400}},
  {{session_id: 'chat-1', session_source: 'webui', updated_at: 300}},
  {{session_id: 'kanban-title-only', session_source: 'webui', title: 'Kanban Session', updated_at: 200}},
  {{session_id: 'kanban-1', session_source: 'kanban', updated_at: 100}},
];
const groups = _buildSidebarSessionGroups(rows, 500);
const background = groups.find(group => group.isBackground);
console.log(JSON.stringify({{
  groups: groups.map(group => ({{label: group.label, ids: group.items.map(row => row.session_id), background: !!group.isBackground}})),
  defaultCollapsed: _isSidebarGroupCollapsed(background, {{}}),
  explicitlyOpen: _isSidebarGroupCollapsed(background, {{'__background_activity__': false}}),
  explicitClosedButActive: _isSidebarGroupCollapsed(background, {{'__background_activity__': true}}, true),
  autoOpen: _isSidebarGroupCollapsed(background, {{}}, true),
  foregroundCollapsed: _isSidebarGroupCollapsed(groups[0], {{}}),
}}));
"""
    result = json.loads(_run_node(script))
    assert result["groups"] == [
        {
            "label": "Today",
            "ids": ["chat-1", "kanban-title-only"],
            "background": False,
        },
        {
            "label": "Background activity (2)",
            "ids": ["tool-1", "kanban-1"],
            "background": True,
        },
    ]
    assert result["defaultCollapsed"] is True
    assert result["explicitlyOpen"] is False
    assert result["explicitClosedButActive"] is False
    assert result["autoOpen"] is False
    assert result["foregroundCollapsed"] is False
