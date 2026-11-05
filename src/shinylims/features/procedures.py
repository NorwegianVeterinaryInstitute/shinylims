'''
procedures.py - UI and server logic for the Links & Procedures view.

Entries come from ``config/procedures.py``. GitHub Markdown is fetched when
someone opens it. Everything else (EK, SharePoint, other web pages) is a
plain link, since those sit behind their own login.
'''

import re

import requests
from faicons import icon_svg
from markdown_it import MarkdownIt
from shiny import reactive, ui

from shinylims.config.procedures import PROCEDURE_ENTRIES

GITHUB_BLOB_URL = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/blob/(?P<ref>[^/]+)/(?P<path>.+\.md)$"
)
FETCH_TIMEOUT_SECONDS = 10

# source -> (badge label, badge icon, action text)
SOURCE_LABELS = {
    "github": ("GitHub", "github", "Read in app"),
    "ek": ("EK", "arrow-up-right-from-square", "Open in EK"),
    "sharepoint": ("SharePoint", "arrow-up-right-from-square", "Open in SharePoint"),
    "link": ("Web", "globe", "Open"),
}

# Raw HTML in the fetched Markdown is escaped rather than injected into the page.
_markdown_parser = MarkdownIt("gfm-like", {"html": False, "linkify": False})


def github_raw_url(blob_url: str) -> str:
    """Turn a GitHub file link into the URL that serves the raw Markdown."""
    match = GITHUB_BLOB_URL.match(blob_url)
    if not match:
        raise ValueError(f"Not a GitHub link to a Markdown file: {blob_url}")
    return "https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}".format(
        **match.groupdict()
    )


def fetch_github_markdown(blob_url: str) -> str:
    response = requests.get(github_raw_url(blob_url), timeout=FETCH_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def render_markdown(text: str) -> ui.HTML:
    return ui.markdown(text, render_func=_markdown_parser.render)


def group_by_category(entries: list[dict]) -> dict[str, list[dict]]:
    """Group entries by category, keeping the order they are configured in."""
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(entry["category"], []).append(entry)
    return groups


def _external_link(label, href: str, class_: str):
    return ui.tags.a(label, href=href, target="_blank", rel="noopener noreferrer", class_=class_)


def _entry_card_body(entry: dict):
    label, icon, action_text = SOURCE_LABELS[entry["source"]]
    action_icon = "arrow-right" if entry["source"] == "github" else "arrow-up-right-from-square"
    action = ui.TagList(action_text, icon_svg(action_icon))

    return ui.div(
        ui.span(
            ui.span(icon_svg(icon), class_="dashboard-card-badge-icon", aria_hidden="true"),
            label,
            class_="dashboard-card-badge availability",
        ),
        ui.span(entry["title"], class_="procedure-card-title"),
        ui.span(entry["description"], class_="procedure-card-description") if entry.get("description") else None,
        ui.span(action, class_="procedure-card-action"),
        class_="procedure-card-body",
    )


def _entry_card(entry: dict):
    """The whole card is the click target: a button for GitHub, a link otherwise."""
    if entry["source"] == "github":
        return ui.input_action_button(
            f"procedure_open_{entry['id']}",
            _entry_card_body(entry),
            class_="procedure-card",
        )
    return _external_link(_entry_card_body(entry), entry["url"], "procedure-card")


def procedures_ui():
    if not PROCEDURE_ENTRIES:
        return ui.p("No links or procedures have been added yet.", class_="text-muted")

    return ui.div(
        *[
            ui.tags.section(
                ui.h3(category, class_="procedures-category-title"),
                ui.div(*[_entry_card(entry) for entry in entries], class_="procedure-list"),
                class_="procedures-category",
            )
            for category, entries in group_by_category(PROCEDURE_ENTRIES).items()
        ],
        class_="procedures-page",
    )


def _markdown_modal(entry: dict):
    try:
        body = render_markdown(fetch_github_markdown(entry["url"]))
    except Exception as e:
        print(f"[procedures] id={entry['id']} error={type(e).__name__}: {e}")
        body = ui.div(
            ui.h4(entry["title"]),
            ui.p("This document could not be loaded from GitHub. Try again, or open it on GitHub instead."),
            ui.p(f"Details: {type(e).__name__}: {e}", class_="text-muted small mb-0"),
            class_="alert alert-warning",
        )

    return ui.modal(
        ui.div(body, class_="procedure-markdown"),
        size="xl",
        easy_close=True,
        footer=ui.TagList(
            _external_link(
                ui.TagList(icon_svg("github"), " View on GitHub"),
                entry["url"],
                "btn btn-outline-secondary",
            ),
            ui.modal_button("Close", class_="btn-secondary"),
        ),
    )


def _register_markdown_viewer(input, entry: dict) -> None:
    @reactive.effect
    @reactive.event(input[f"procedure_open_{entry['id']}"])
    def _open():
        ui.modal_show(_markdown_modal(entry))


def procedures_server(input):
    for entry in PROCEDURE_ENTRIES:
        if entry["source"] == "github":
            _register_markdown_viewer(input, entry)
