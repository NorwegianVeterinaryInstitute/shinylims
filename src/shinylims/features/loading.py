"""Shared loading modal helpers for lab tools."""

from shiny import ui


def build_tool_loading_modal(*, title: str, message: str, detail: str | None = None):
    """Return a shared loading modal used by lab-tool LIMS workflows."""
    copy_children: list[ui.TagChild] = [
        ui.span(message, class_="tool-loading-modal-message"),
    ]
    if detail:
        copy_children.append(ui.p(detail, class_="tool-loading-modal-detail mb-0"))

    return ui.modal(
        ui.div(
            ui.tags.div(
                class_="spinner-border text-primary tool-loading-modal-spinner",
                role="status",
                aria_hidden="true",
            ),
            ui.div(*copy_children, class_="tool-loading-modal-copy"),
            class_="tool-loading-modal-body",
        ),
        title=title,
        easy_close=False,
        footer=None,
    )
