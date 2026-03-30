"""
app.py - Main UI and server logic for the Shiny LIMS Metadata App.

This module defines a single-page dashboard shell that routes users from one
front page into the individual table and tool views.
"""

from datetime import datetime
from pathlib import Path
import re

import pandas as pd
import pytz
from faicons import icon_svg
from shiny import App, reactive, render, ui

from shinylims.features.projects import projects_server, projects_ui
from shinylims.features.reagent_overview import (
    reagent_overview_server,
    reagent_overview_ui,
)
from shinylims.features.reagents import reagents_server, reagents_ui
from shinylims.features.samples import samples_server, samples_ui
from shinylims.features.sequencing import seq_server, seq_ui
from shinylims.features.storage import storage_server, storage_ui
from shinylims.integrations.data_utils import (
    fetch_all_samples_data,
    fetch_historical_samples_data,
    fetch_projects_data,
    fetch_sequencing_data,
    get_app_version,
)
from shinylims.security import (
    is_allowed_reagents_user,
    reagents_access_policy_summary,
)


css_path = Path(__file__).parent / "assets" / "styles.css"


####################
# APP CONFIGURATION #
####################

# Shouldnt be needed, but something in the project layout is confusing Shiny's default static path discovery
www_dir = Path(__file__).parent / "www"

logo_path = "images/favicon/favicon-96x96.png"
app_version = get_app_version()
access_request_email = "hts@vetinst.no"

DASHBOARD_SECTIONS = [
    {
        "id": "metadata",
        "title": "Metadata Tables",
        "description": "Browse the synced Clarity LIMS datasets.",
        "cards": [
            {
                "view": "projects",
                "button_id": "open_table_projects",
                "icon": "folder",
                "eyebrow": "Metadata Table",
                "title": "Projects",
                "description": "Browse project-level metadata from Clarity LIMS.",
            },
            {
                "view": "samples",
                "button_id": "open_table_samples",
                "icon": "flask",
                "eyebrow": "Metadata Table",
                "title": "Samples",
                "description": "Explore sample metadata. Integration to SAGA (ATLAS tool).",
            },
            {
                "view": "sequencing",
                "button_id": "open_table_sequencing",
                "icon": "dna",
                "eyebrow": "Metadata Table",
                "title": "Illumina Sequencing",
                "description": "Inspect sequencing run metadata and performance metrics.",
            },
        ],
    },
    {
        "id": "tools",
        "title": "Lab Tools",
        "description": "Access reagent-focused tools and DNA storage box overview.",
        "cards": [
            {
                "view": "reagents",
                "button_id": "open_tool_reagents",
                "icon": "box",
                "eyebrow": "Lab Tool",
                "title": "Reagent Lot Registration",
                "description": "Create and submit reagent lots to Clarity LIMS.",
                "restricted": "Approved reagent users",
            },
            {
                "view": "reagent_overview",
                "button_id": "open_tool_index_plate_maps",
                "icon": "vial",
                "eyebrow": "Lab Tool",
                "title": "Reagent Overview",
                "description": "Review prep sets, sequencing stock, and index plates.",
                "restricted": "Approved reagent users",
            },
            {
                "view": "storage",
                "button_id": "open_tool_storage",
                "icon": "boxes-stacked",
                "eyebrow": "Lab Tool",
                "title": "Storage Box Status",
                "description": "View populated and discarded DNA storage containers.",
            },
        ],
    },
]

VIEW_DETAILS = {
    "projects": {
        "eyebrow": "Metadata Table",
        "title": "Projects",
        "description": "Browse project-level metadata from Clarity LIMS.",
    },
    "samples": {
        "eyebrow": "Metadata Table",
        "title": "Samples",
        "description": "Explore and export sample metadata.",
    },
    "sequencing": {
        "eyebrow": "Metadata Table",
        "title": "Illumina Sequencing",
        "description": "Inspect sequencing run metadata and metrics from completed runs.",
    },
    "reagents": {
        "eyebrow": "Lab Tool",
        "title": "Reagent Lot Registration",
        "description": "Create and submit reagent lots to Clarity LIMS.",
    },
    "reagent_overview": {
        "eyebrow": "Lab Tool",
        "title": "Reagent Overview",
        "description": "Review prep sets, sequencing stock, and index plates.",
    },
    "storage": {
        "eyebrow": "Lab Tool",
        "title": "Storage Box Status",
        "description": "View populated and discarded DNA for NGS storage containers.",
    },
}


def _dashboard_card(card: dict[str, str], *, current_user_blocked: bool = False):
    badges = []
    restricted_group = card.get("restricted")
    if restricted_group:
        badges.append(
            ui.span(
                ui.span(icon_svg("lock"), class_="dashboard-card-badge-icon", aria_hidden="true"),
                ui.span("Restricted access"),
                class_="dashboard-card-badge restricted",
            )
        )

    action_id = f"blocked_{card['view']}" if current_user_blocked else card["button_id"]

    return ui.input_action_button(
        action_id,
        ui.div(
            ui.div(
                ui.h3(
                    ui.span(
                        icon_svg(card["icon"]),
                        class_="dashboard-card-inline-icon",
                        aria_hidden="true",
                    ),
                    ui.span(card["title"]),
                    class_="dashboard-card-title",
                ),
                ui.div(
                    (
                        ui.div(*badges, class_="dashboard-card-badges")
                        if current_user_blocked and badges
                        else None
                    ),
                    (
                        ui.span(
                            icon_svg("arrow-right"),
                            class_="dashboard-card-arrow",
                            aria_hidden="true",
                        )
                        if not current_user_blocked
                        else None
                    ),
                    class_="dashboard-card-heading-meta",
                ),
                class_="dashboard-card-heading",
            ),
            ui.p(card["description"], class_="dashboard-card-description"),
            class_="dashboard-card-body",
        ),
        class_="dashboard-card dashboard-card-trigger w-100 h-100",
    )


def _dashboard_section(section: dict[str, object], *, blocked_views: set[str] | None = None):
    blocked_views = blocked_views or set()
    cards = [
        _dashboard_card(card, current_user_blocked=card["view"] in blocked_views)
        for card in section["cards"]
    ]
    return ui.div(
        ui.div(
            ui.h2(section["title"], class_="dashboard-section-title"),
            ui.p(section["description"], class_="dashboard-section-description"),
            class_="dashboard-section-header",
        ),
        ui.layout_columns(*cards, col_widths=[4] * len(cards)),
        class_="dashboard-section",
    )


def _detail_shell(view_name: str, *body_children):
    view = VIEW_DETAILS[view_name]

    return ui.div(
        ui.div(
            ui.div(
                ui.input_action_button(
                    "back_to_dashboard",
                    "← Back",
                    class_="btn btn-outline-secondary btn-sm detail-back-button",
                ),
                ui.div(
                    ui.div(view["eyebrow"], class_="detail-eyebrow"),
                    ui.h2(view["title"], class_="detail-title"),
                    ui.p(view["description"], class_="detail-description"),
                    class_="detail-copy",
                ),
                ui.div(
                    ui.output_ui("detail_toolbar"),
                    class_="detail-header-actions",
                ),
                class_="detail-header compact",
            ),
            *body_children,
            class_="detail-page",
        ),
        class_="app-page",
    )


def _restricted_tool_card(title: str):
    return ui.card(
        ui.card_header(title),
        ui.card_body(
            ui.h5("You do not have access"),
            ui.p(
                f"Allowed access is {reagents_access_policy_summary()}.",
                class_="text-muted mb-1",
            ),
            ui.p(
                "Contact admin to be added as an individual user if needed.",
                class_="text-muted mb-0",
            ),
            ui.p(
                "Request access via ",
                ui.tags.a(
                    access_request_email,
                    href=f"mailto:{access_request_email}",
                ),
                ".",
                class_="mt-3 mb-0",
            ),
        ),
        class_="border-danger",
    )


####################
# CONSTRUCT THE UI #
####################

app_ui = ui.page_fluid(
    ui.head_content(
        ui.tags.meta(
            name="viewport",
            content="width=device-width, initial-scale=1.0, maximum-scale=1.0",
        ),
        ui.tags.link(
            rel="icon",
            type="image/png",
            sizes="32x32",
            href="images/favicon/favicon-32x32.png",
        ),
        ui.tags.link(
            rel="icon",
            type="image/png",
            sizes="16x16",
            href="images/favicon/favicon-16x16.png",
        ),
        ui.tags.link(
            rel="icon",
            type="image/png",
            sizes="96x96",
            href="images/favicon/favicon-96x96.png",
        ),
        ui.include_css(css_path),
    ),
    ui.output_ui("render_updated_data"),
    ui.div(
        ui.output_ui("app_header"),
        ui.output_ui("app_content"),
        class_="app-shell",
    ),
    theme=ui.Theme.from_brand(__file__),
)


####################
# DATASET CACHE    #
####################

class DatasetCache:
    """Per-session cache for the four live datasets loaded from Clarity Postgres."""

    def __init__(self):
        self._projects = reactive.Value(pd.DataFrame())
        self._samples = reactive.Value(pd.DataFrame())
        self._historical = reactive.Value(pd.DataFrame())
        self._seq = reactive.Value(pd.DataFrame())

        self._projects_meta = reactive.Value(None)
        self._samples_meta = reactive.Value(None)
        self._seq_meta = reactive.Value(None)

        self._projects_loaded = reactive.Value(False)
        self._samples_loaded = reactive.Value(False)
        self._historical_loaded = reactive.Value(False)
        self._seq_loaded = reactive.Value(False)

    # --- Accessors (callable, can be passed directly to feature server functions) ---

    def projects(self) -> pd.DataFrame:
        return self._projects.get()

    def samples(self) -> pd.DataFrame:
        return self._samples.get()

    def historical(self) -> pd.DataFrame:
        return self._historical.get()

    def seq(self) -> pd.DataFrame:
        return self._seq.get()

    # --- Loaders ---

    def load_projects(self, force: bool = False) -> None:
        if self._projects_loaded.get() and not force:
            return
        df, meta = fetch_projects_data()
        self._projects.set(df)
        self._projects_meta.set(meta)
        self._projects_loaded.set(True)

    def load_samples(self, force: bool = False) -> None:
        if self._samples_loaded.get() and not force:
            return
        df, meta = fetch_all_samples_data()
        self._samples.set(df)
        self._samples_meta.set(meta)
        self._samples_loaded.set(True)

    def load_historical(self, force: bool = False) -> None:
        if self._historical_loaded.get() and not force:
            return
        df = fetch_historical_samples_data()
        self._historical.set(df)
        self._historical_loaded.set(True)

    def load_sequencing(self, force: bool = False) -> None:
        if self._seq_loaded.get() and not force:
            return
        df, meta = fetch_sequencing_data()
        self._seq.set(df)
        self._seq_meta.set(meta)
        self._seq_loaded.set(True)

    # --- State queries ---

    def is_projects_loaded(self) -> bool:
        return self._projects_loaded.get()

    def is_samples_loaded(self) -> bool:
        return self._samples_loaded.get()

    def is_historical_loaded(self) -> bool:
        return self._historical_loaded.get()

    def is_seq_loaded(self) -> bool:
        return self._seq_loaded.get()

    def refresh_loaded(self) -> list[tuple[str, object]]:
        """Return (label, loader) pairs for all currently-loaded datasets."""
        loaders = []
        if self._projects_loaded.get():
            loaders.append(("projects", lambda: self.load_projects(force=True)))
        if self._samples_loaded.get():
            loaders.append(("samples", lambda: self.load_samples(force=True)))
        if self._historical_loaded.get():
            loaders.append(("historical samples", lambda: self.load_historical(force=True)))
        if self._seq_loaded.get():
            loaders.append(("sequencing", lambda: self.load_sequencing(force=True)))
        return loaders

    def timestamps(self) -> dict[str, str | None]:
        return {
            "projects": self._projects_meta.get(),
            "samples": self._samples_meta.get(),
            "ilmn_sequencing": self._seq_meta.get(),
        }


###################
# SERVER FUNCTION #
###################


def _metadata_backend_label() -> str:
    """Return a short user-facing label for the live metadata backend."""
    return "Clarity Postgres"


def _format_dataset_load_error(error: Exception) -> str:
    """Return a concise user-facing error for metadata load failures."""
    details = f"{type(error).__name__}: {error}"
    return (
        "Clarity Postgres is unavailable, so metadata could not be loaded. "
        "This usually means the database is unreachable from your current network, "
        "for example because your IP is not whitelisted. "
        f"Details: {details}"
    )


def server(input, output, session):
    """
    Fetch data and wire the single-page dashboard/detail views.
    """
    current_view = reactive.Value("dashboard")
    cache = DatasetCache()

    reagents_server(input, output, session)
    reagent_overview_server(input, output, session)
    storage_server()

    projects_server(cache.projects)
    samples_server(cache.samples, cache.historical, input)
    seq_server(cache.seq)

    db_warning_state = reactive.Value(None)
    shown_db_warning_state = reactive.Value(None)

    def _run_load_step(step_label: str, loader) -> None:
        try:
            loader()
            db_warning_state.set(None)
        except Exception as e:
            warning = _format_dataset_load_error(e)
            print(f"[app-load] step={step_label} backend={_metadata_backend_label()} error={warning}")
            db_warning_state.set(warning)
            raise

    def update_database_data():
        """Refresh only the datasets that have already been loaded in this session."""
        with ui.Progress(min=1, max=5) as p:
            p.set(message="Refreshing loaded datasets...")

            active_loaders = cache.refresh_loaded()
            if not active_loaders:
                active_loaders = [
                    ("projects", cache.load_projects),
                    ("samples", cache.load_samples),
                    ("sequencing", cache.load_sequencing),
                ]

            for idx, (label, loader) in enumerate(active_loaders, start=1):
                p.set(idx, message=f"Refreshing {label}...")
                _run_load_step(label, loader)

            p.set(5, message="Loaded datasets refreshed")

    def _format_display_timestamp(raw_timestamp: str | None) -> str:
        if not raw_timestamp:
            return "Not available"
        try:
            return datetime.fromisoformat(raw_timestamp).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return raw_timestamp

    def get_update_display_info():
        """Return simple display strings for tooltip/info modal."""
        ts = cache.timestamps()
        display_info = {
            key: _format_display_timestamp(ts[key]) if ts[key] else "Not loaded yet"
            for key in ("projects", "samples", "ilmn_sequencing")
        }
        display_info["app_refresh"] = datetime.now(pytz.timezone("Europe/Oslo")).strftime("%Y-%m-%d %H:%M")
        return display_info

    @reactive.Effect
    @reactive.event(input.open_table_projects)
    def _open_projects():
        current_view.set("projects")
        if not cache.is_projects_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading projects...")
                _run_load_step("projects", cache.load_projects)

    @reactive.Effect
    @reactive.event(input.open_table_samples)
    def _open_samples():
        current_view.set("samples")
        if not cache.is_samples_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading samples...")
                _run_load_step("samples", cache.load_samples)

    @reactive.Effect
    @reactive.event(input.open_table_sequencing)
    def _open_sequencing():
        current_view.set("sequencing")
        if not cache.is_seq_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading sequencing...")
                _run_load_step("sequencing", cache.load_sequencing)

    @reactive.Effect
    @reactive.event(input.open_tool_reagents)
    def _open_reagents():
        current_view.set("reagents")

    @reactive.Effect
    @reactive.event(input.open_tool_index_plate_maps)
    def _open_reagent_overview():
        current_view.set("reagent_overview")

    @reactive.Effect
    @reactive.event(input.open_tool_storage)
    def _open_storage():
        current_view.set("storage")

    @reactive.Effect
    @reactive.event(input.back_to_dashboard)
    def _back_to_dashboard():
        current_view.set("dashboard")

    @reactive.Effect
    def _load_historical_samples_when_enabled():
        if current_view.get() != "samples" or not input.include_hist():
            return
        with ui.Progress(min=1, max=1) as p:
            p.set(message="Loading historical samples...")
            _run_load_step("historical samples", cache.load_historical)

    @reactive.Effect
    @reactive.event(input.update_button)
    def on_update_button_click():
        """Handle the update button click event."""
        update_database_data()

    @reactive.Effect
    def show_db_warning_notification():
        warning = db_warning_state.get()
        if not warning or shown_db_warning_state.get() == warning:
            return

        shown_db_warning_state.set(warning)
        ui.notification_show(
            warning,
            duration=None,
            type="error",
        )

    @output
    @render.ui
    def app_header():
        if current_view.get() != "dashboard":
            return None

        return ui.div(
            ui.div(
                ui.tags.img(
                    src=logo_path,
                    alt="NVI",
                    height="44px",
                    class_="app-logo",
                ),
                ui.div(
                    ui.h1("ShinyClarity", class_="app-brand-title"),
                    ui.div("Metadata and Lab Tools for NGS", class_="app-brand-subtitle"),
                    class_="app-brand-copy",
                ),
                class_="app-brand",
            ),
            ui.div(
                ui.div(
                    ui.input_action_button(
                        "info_button",
                        icon_svg("info"),
                        class_="btn btn-outline-primary app-icon-button",
                    ),
                    class_="app-toolbar",
                ),
                class_="app-header-side",
            ),
            class_="app-header",
        )

    @output
    @render.ui
    def detail_toolbar():
        if current_view.get() == "dashboard":
            return None

        metadata_table_views = {"projects", "samples", "sequencing"}
        toolbar_children = []
        if db_warning_state.get():
            toolbar_children.append(
                ui.span("Database error", class_="badge text-bg-danger detail-toolbar-warning")
            )

        if current_view.get() == "samples":
            toolbar_children.append(
                ui.div(
                    ui.input_switch("include_hist", "Historical samples", False),
                    class_="detail-toolbar-switch",
                )
            )

        if current_view.get() in metadata_table_views:
            toolbar_children.extend(
                [
                    ui.input_action_button(
                        "info_button",
                        icon_svg("info"),
                        class_="btn btn-outline-primary btn-sm detail-icon-button",
                    ),
                    ui.tooltip(
                        ui.input_action_button(
                            "update_button",
                            "Refresh data",
                            class_="btn btn-outline-primary btn-sm detail-refresh-button",
                        ),
                        ui.output_ui("update_tooltip_output"),
                        placement="left",
                        id="detail_update_tooltip",
                    ),
                ]
            )

        if not toolbar_children:
            return None

        return ui.div(*toolbar_children, class_="detail-toolbar")

    @output
    @render.ui
    def update_tooltip_output():
        """Render tooltip content about metadata freshness and current load status."""
        formatted_info = get_update_display_info()
        return ui.div(
            ui.tags.strong("Loaded from live Clarity Postgres:"),
            ui.tags.br(),
            f"Projects: {formatted_info['projects']}",
            ui.tags.br(),
            f"Samples: {formatted_info['samples']}",
            ui.tags.br(),
            f"Sequencing: {formatted_info['ilmn_sequencing']}",
            ui.tags.br(),
            ui.tags.br(),
            ui.tags.strong("App last refreshed:"),
            ui.tags.br(),
            formatted_info["app_refresh"],
            ui.tags.br() if db_warning_state.get() else None,
            ui.tags.br() if db_warning_state.get() else None,
            ui.tags.strong("Current database error:") if db_warning_state.get() else None,
            ui.tags.br() if db_warning_state.get() else None,
            db_warning_state.get() if db_warning_state.get() else None,
        )

    @reactive.Effect
    @reactive.event(input.info_button)
    def on_info_button_click():
        """Handle the info button click event."""
        formatted_info = get_update_display_info()
        ui.modal_show(
            ui.modal(
                ui.h2("ShinyClarity Information", class_="mb-4"),
                ui.div(
                    ui.h3("About"),
                    ui.p(
                        """This app provides a user-friendly interface to explore and filter LIMS metadata.
                         It connects to the LIMS database and displays information about projects, samples,
                         and sequencing runs."""
                    ),
                    ui.h3("Database Information"),
                    ui.p(
                        "Projects, samples, sequencing runs, and storage boxes are read directly from the live Clarity Postgres database when those views are opened."
                    ),
                    ui.p(
                        "Historical samples are still served from the legacy SQLite pin when the historical switch is enabled."
                    ),
                    ui.h4("Last Loaded Timestamps:"),
                    ui.tags.dl(
                        ui.tags.dt("Projects"),
                        ui.tags.dd(formatted_info["projects"]),
                        ui.tags.dt("Samples"),
                        ui.tags.dd(formatted_info["samples"]),
                        ui.tags.dt("Sequencing"),
                        ui.tags.dd(formatted_info["ilmn_sequencing"]),
                        ui.tags.dt("App Last Refreshed"),
                        ui.tags.dd(formatted_info["app_refresh"]),
                        class_="row",
                    ),
                    ui.h3("Data Fields Collection"),
                    ui.h4("Projects"),
                    ui.p(
                        "Project rows are built directly from the Clarity Postgres schema and related UDF views."
                    ),
                    ui.h4("Samples"),
                    ui.p(ui.tags.strong("Extraction step"), ": Extraction Number"),
                    ui.p(
                        ui.tags.strong("Fluorescence step"),
                        ": Absorbance, A260/280 ratio, A260/230 ratio, Fluorescence, Storage Box Name, Storage Well",
                    ),
                    ui.p(
                        ui.tags.strong("Prep Step"),
                        ": Experiment Name, Reagent Labels",
                    ),
                    ui.p(
                        ui.tags.strong("Billing Step"),
                        ": Invoice ID, Price, Billing Description",
                    ),
                    ui.p(
                        "Note that the step must be completed in LIMS before the data fields are updated in the Shiny App."
                    ),
                    ui.h4("Sequencing"),
                    ui.p(
                        ui.tags.strong("Step 8 (NS/MS Run)"),
                        ": Technician Name, Species, Experiment Name, Comment, Run ID, Flow Cell ID, Reagent Cartridge ID, Date",
                    ),
                    ui.p(
                        ui.tags.strong("Step 7 (Generate SampleSheet)"),
                        ": Read 1 Cycles, Read 2 Cycles, Index Cycles",
                    ),
                    ui.p(
                        ui.tags.strong("Step 6 (Make Final Loading Dilution)"),
                        ": Final Library Loading (pM), Volume 20pM Denat Sample (µl), PhiX / library spike-in (%), Average Size - bp",
                    ),
                    ui.p(
                        "Table will not be updated until the sequencing step has been completed."
                    ),
                    ui.h3("App Version"),
                    ui.p(f"Version: {app_version}"),
                    class_="p-4",
                    style="max-height: 70vh; overflow-y: auto;",
                ),
                size="l",
                easy_close=True,
                id="info_modal",
            )
        )

    def show_restricted_access_modal(tool_name: str) -> None:
        ui.modal_show(
            ui.modal(
                ui.p(f"You do not currently have access to {tool_name}."),
                ui.p(
                    "If you need access, contact HTS at ",
                    ui.tags.a(
                        access_request_email,
                        href=f"mailto:{access_request_email}",
                    ),
                    ".",
                ),
                title="Restricted Access",
                easy_close=True,
                footer=ui.modal_button("Close", class_="btn-secondary"),
            )
        )

    @reactive.Effect
    @reactive.event(input.blocked_reagents)
    def show_reagents_access_denied():
        show_restricted_access_modal("Reagent Lot Registration")

    @reactive.Effect
    @reactive.event(input.blocked_reagent_overview)
    def show_reagent_overview_access_denied():
        show_restricted_access_modal("Reagent Overview")

    @output
    @render.ui
    def app_content():
        if current_view.get() == "dashboard":
            blocked_views: set[str] = set()
            if not is_allowed_reagents_user(session):
                blocked_views.update({"reagents", "reagent_overview"})

            return ui.div(
                *[
                    _dashboard_section(section, blocked_views=blocked_views)
                    for section in DASHBOARD_SECTIONS
                ],
                class_="app-page dashboard-page",
            )

        if current_view.get() == "projects":
            return _detail_shell("projects", projects_ui())

        if current_view.get() == "samples":
            return _detail_shell("samples", samples_ui())

        if current_view.get() == "sequencing":
            return _detail_shell("sequencing", seq_ui())

        if current_view.get() == "reagents":
            if not is_allowed_reagents_user(session):
                return _detail_shell(
                    "reagents",
                    _restricted_tool_card("Reagent Lot Registration"),
                )
            return _detail_shell("reagents", reagents_ui(show_title=False))

        if current_view.get() == "reagent_overview":
            if not is_allowed_reagents_user(session):
                return _detail_shell(
                    "reagent_overview",
                    _restricted_tool_card("Reagent Overview"),
                )
            return _detail_shell(
                "reagent_overview",
                reagent_overview_ui(show_title=False),
            )

        return _detail_shell("storage", storage_ui())

    @output
    @render.ui
    def render_updated_data():
        """Provide a placeholder output so table modules are initialized once above."""
        return ui.TagList()


###########
# RUN APP #
###########

app = App(app_ui, server, static_assets=www_dir)
