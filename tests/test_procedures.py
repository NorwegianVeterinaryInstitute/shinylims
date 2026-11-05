from __future__ import annotations

import re

import pytest

from shinylims.config.procedures import PROCEDURE_ENTRIES, PROCEDURE_SOURCES
from shinylims.features import procedures
from shinylims.features.procedures import (
    github_raw_url,
    group_by_category,
    procedures_ui,
    render_markdown,
)


def _entry(**overrides) -> dict:
    entry = {
        "id": "doc",
        "title": "Doc",
        "description": "",
        "category": "General",
        "source": "ek",
        "url": "https://vetinst.dkhosting.no/",
    }
    entry.update(overrides)
    return entry


# ── github_raw_url ───────────────────────────────────────────────────────────

def test_github_raw_url_converts_blob_link():
    url = "https://github.com/NorwegianVeterinaryInstitute/Repo/blob/master/docs/guide.md"
    assert github_raw_url(url) == (
        "https://raw.githubusercontent.com/NorwegianVeterinaryInstitute/Repo/master/docs/guide.md"
    )


def test_github_raw_url_keeps_commit_sha_as_ref():
    url = "https://github.com/org/repo/blob/0a1b2c3/guide.md"
    assert github_raw_url(url) == "https://raw.githubusercontent.com/org/repo/0a1b2c3/guide.md"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/org/repo/blob/master/guide.pdf",
        "https://github.com/org/repo/tree/master/docs/guide.md",
        "https://example.com/org/repo/blob/master/guide.md",
    ],
)
def test_github_raw_url_rejects_other_links(url):
    with pytest.raises(ValueError):
        github_raw_url(url)


# ── render_markdown ──────────────────────────────────────────────────────────

def test_render_markdown_escapes_raw_html():
    html = str(render_markdown("<script>alert(1)</script>"))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_markdown_renders_tables():
    html = str(render_markdown("| a |\n| - |\n| 1 |"))
    assert "<table>" in html


# ── group_by_category ────────────────────────────────────────────────────────

def test_group_by_category_keeps_configured_order():
    entries = [
        _entry(id="a", category="Second"),
        _entry(id="b", category="First"),
        _entry(id="c", category="Second"),
    ]
    groups = group_by_category(entries)
    assert list(groups) == ["Second", "First"]
    assert [e["id"] for e in groups["Second"]] == ["a", "c"]


# ── configured entries ───────────────────────────────────────────────────────

def test_configured_entry_ids_are_unique_and_safe():
    ids = [entry["id"] for entry in PROCEDURE_ENTRIES]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[A-Za-z0-9_]+", entry_id) for entry_id in ids)


@pytest.mark.parametrize("entry", PROCEDURE_ENTRIES, ids=lambda e: e["id"])
def test_configured_entry_is_complete(entry):
    assert entry["title"]
    assert entry["category"]
    assert entry["source"] in PROCEDURE_SOURCES
    if entry["source"] == "github":
        github_raw_url(entry["url"])
    else:
        assert entry["url"].startswith("https://")


# ── procedures_ui ────────────────────────────────────────────────────────────

def test_procedures_ui_renders_one_action_per_source(monkeypatch):
    monkeypatch.setattr(
        procedures,
        "PROCEDURE_ENTRIES",
        [
            _entry(id="md", source="github", url="https://github.com/o/r/blob/main/a.md"),
            _entry(id="ek", source="ek", url="https://vetinst.dkhosting.no/doc"),
            _entry(id="sp", source="sharepoint", url="https://vetinst.sharepoint.com/doc"),
            _entry(id="web", source="link", url="https://example.org/portal"),
        ],
    )
    html = str(procedures_ui())
    assert 'id="procedure_open_md"' in html
    assert 'href="https://vetinst.dkhosting.no/doc"' in html
    assert "Open in EK" in html
    assert 'href="https://vetinst.sharepoint.com/doc"' in html
    assert "Open in SharePoint" in html
    assert 'href="https://example.org/portal"' in html
    assert html.count('target="_blank"') == 3


def test_procedures_ui_handles_no_entries(monkeypatch):
    monkeypatch.setattr(procedures, "PROCEDURE_ENTRIES", [])
    assert "No links or procedures" in str(procedures_ui())
