"""
app.py - Main UI and server logic for the Shiny LIMS Metadata App.

This module defines a single-page dashboard shell that routes users from one
front page into the individual table and tool views.
"""

from datetime import datetime
import os
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
from shinylims.features.samples import (
    project_limsids_for_seq_limsids,
    seq_limsids_for_project_limsids,
    samples_server,
    samples_ui,
)
from shinylims.features.sequencing import seq_server, seq_ui
from shinylims.features.storage import storage_server, storage_ui
from shinylims.integrations.clarity_pg import (
    get_clarity_pg_env_diagnostics,
    get_clarity_pg_network_diagnostics,
    get_clarity_pg_ssl_diagnostics,
)
from shinylims.integrations.data_utils import (
    fetch_all_samples_data,
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
LEGACY_METADATA_DOWNLOADS = [
    {
        "id": "legacy_sample_prep",
        "label": "Sample Prep Log",
        "description": "Archived sample preparation log from before November 2023.",
        "pin_name": "vi2172/legacy_metadata_sample_prep",
    },
    {
        "id": "legacy_sequencing_log",
        "label": "Sequencing Log",
        "description": "Archived sequencing log from before November 2023.",
        "pin_name": "vi2172/legacy_metadata_sequencing_log",
    },
]

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
                "availability_note": "Nov 2023+",
            },
            {
                "view": "samples",
                "button_id": "open_table_samples",
                "icon": "flask",
                "eyebrow": "Metadata Table",
                "title": "Samples",
                "description": "Explore sample metadata. Integration to SAGA (ATLAS tool).",
                "availability_note": "Nov 2023+",
            },
            {
                "view": "sequencing",
                "button_id": "open_table_sequencing",
                "icon": "dna",
                "eyebrow": "Metadata Table",
                "title": "Illumina Sequencing",
                "description": "Inspect sequencing run metadata and performance metrics.",
                "availability_note": "Nov 2023+",
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
    if restricted_group and current_user_blocked:
        badges.append(
            ui.span(
                ui.span(icon_svg("lock"), class_="dashboard-card-badge-icon", aria_hidden="true"),
                ui.span("Restricted access"),
                class_="dashboard-card-badge restricted",
            )
        )
    if card.get("availability_note"):
        badges.append(
            ui.span(
                ui.span(card["availability_note"]),
                class_="dashboard-card-badge availability",
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
                        if badges
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


def _dashboard_archive_disclosure() -> object:
    """Render the pre-Nov-2023 archive as a collapsed, de-emphasized disclosure.

    Uses a native ``<details>`` element (collapsed by default) so the rarely-used
    archive stays out of the way but remains reachable, with the download cards
    revealed inline on expand.
    """
    return ui.tags.details(
        ui.tags.summary(
            ui.span(icon_svg("box-archive"), class_="dashboard-archive-icon", aria_hidden="true"),
            ui.span("Archived metadata (before November 2023)"),
            ui.span(
                icon_svg("chevron-right"),
                class_="dashboard-archive-chevron",
                aria_hidden="true",
            ),
            class_="dashboard-archive-summary",
        ),
        ui.div(
            _metadata_archive_ui(),
            class_="dashboard-archive-body",
        ),
        class_="dashboard-archive-disclosure",
    )


def _dashboard_section(section: dict[str, object], *, blocked_views: set[str] | None = None):
    blocked_views = blocked_views or set()
    cards = section["cards"]
    if section["id"] == "metadata":
        live_cards = [
            _dashboard_card(card, current_user_blocked=card["view"] in blocked_views)
            for card in cards
        ]
        content = [
            ui.layout_columns(*live_cards, col_widths=[4] * len(live_cards)),
        ]
        if LEGACY_METADATA_DOWNLOADS:
            content.append(_dashboard_archive_disclosure())
    else:
        rendered_cards = [
            _dashboard_card(card, current_user_blocked=card["view"] in blocked_views)
            for card in cards
        ]
        content = [ui.layout_columns(*rendered_cards, col_widths=[4] * len(rendered_cards))]

    return ui.div(
        ui.div(
            ui.h2(section["title"], class_="dashboard-section-title"),
            ui.p(section["description"], class_="dashboard-section-description"),
            class_="dashboard-section-header",
        ),
        *content,
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


def _legacy_metadata_download_card(item: dict) -> object:
    """Render a single archive metadata download card."""
    return ui.card(
        ui.card_header(item["label"]),
        ui.card_body(
            ui.p(item["description"]),
            ui.download_button(item["id"], "Download file", class_="btn-outline-primary btn-sm"),
        ),
        class_="h-100",
    )


def _metadata_archive_ui() -> object:
    """Render the archive download view for metadata before November 2023."""
    download_cards = [
        _legacy_metadata_download_card(item)
        for item in LEGACY_METADATA_DOWNLOADS
    ]
    return ui.div(
        ui.p(
            "These archive downloads are intended for metadata recorded before November 2023, before the current live Clarity Postgres-backed tables begin."
        ),
        ui.layout_columns(*download_cards, col_widths=[4] * len(download_cards)),
        class_="d-flex flex-column gap-3",
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
        # This app is deliberately light-only (see the `color-scheme: light
        # !important` rule in styles.css), but itables >=2.9 independently
        # watches `prefers-color-scheme` in JS and adds a `dark` class to
        # <html> regardless of that CSS. Its bundled stylesheet then applies
        # dozens of dark-theme rules scoped to `html.dark` -- e.g. table body
        # text turning near-white, unreadable against this app's light
        # background. Rather than override each such rule as it's found,
        # strip the class the instant itables (or anything else) adds it.
        ui.tags.script("""
            (function() {
                var html = document.documentElement;
                function stripDark() {
                    if (html.classList.contains('dark')) {
                        html.classList.remove('dark');
                    }
                }
                stripDark();
                new MutationObserver(stripDark).observe(html, {
                    attributes: true,
                    attributeFilter: ['class'],
                });
            })();
        """),
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
        self._seq = reactive.Value(pd.DataFrame())

        self._projects_meta = reactive.Value(None)
        self._samples_meta = reactive.Value(None)
        self._seq_meta = reactive.Value(None)

        self._projects_loaded = reactive.Value(False)
        self._samples_loaded = reactive.Value(False)
        self._seq_loaded = reactive.Value(False)

    # --- Accessors (callable, can be passed directly to feature server functions) ---

    def projects(self) -> pd.DataFrame:
        return self._projects.get()

    def samples(self) -> pd.DataFrame:
        return self._samples.get()

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

    def is_seq_loaded(self) -> bool:
        return self._seq_loaded.get()

    def refresh_loaded(self) -> list[tuple[str, object]]:
        """Return (label, loader) pairs for all currently-loaded datasets."""
        loaders = []
        if self._projects_loaded.get():
            loaders.append(("projects", lambda: self.load_projects(force=True)))
        if self._samples_loaded.get():
            loaders.append(("samples", lambda: self.load_samples(force=True)))
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


def _format_ssl_modal_info() -> dict[str, str]:
    """Return a concise user-facing SSL summary for the info modal."""
    diagnostics = get_clarity_pg_ssl_diagnostics()

    info = {
        "connection_security": "Unavailable",
    }

    if not diagnostics.get("connection_ok"):
        return info

    if not diagnostics.get("ssl_status_available"):
        return info

    if diagnostics.get("ssl_in_use"):
        tls_version = str(diagnostics.get("ssl_version") or "").strip()
        info["connection_security"] = (
            f"Encrypted ({tls_version})" if tls_version else "Encrypted"
        )
    else:
        info["connection_security"] = "Not encrypted"
    return info


def _info_table(rows: list[tuple[str, str]]) -> object:
    """Build a compact two-column table for info-modal summaries."""
    body_rows = [
        ui.tags.tr(
            ui.tags.th(label, scope="row", class_="text-nowrap"),
            ui.tags.td(value),
        )
        for label, value in rows
    ]
    return ui.tags.table(
        ui.tags.tbody(*body_rows),
        class_="table table-sm table-borderless align-middle mb-0",
    )


def _build_data_field_sources_accordion() -> object:
    """Describe the data-entry points and lineage/UDF sourcing used by the app."""
    return ui.accordion(
        ui.accordion_panel(
            "Projects",
            ui.p(
                "Entry point: project records in the Clarity project table."
            ),
            ui.p(
                "Fields such as project LIMS ID, dates, project name, submitter, and lab are read directly from the project, researcher, and lab tables."
            ),
            ui.p(
                "Species is aggregated by joining project-linked samples and reading the sample-level Species UDF from the sample UDF view."
            ),
            ui.p(
                "Project comments are read from the entity UDF view using the project-attached 'Message to the lab' field."
            ),
            value="projects",
        ),
        ui.accordion_panel(
            "Samples",
            ui.p(
                "Entry point: sample entities in the Clarity sample table."
            ),
            ui.p(
                "Fields such as sample LIMS ID, project, received date, sample name, submitter, and lab are built directly from sample, project, researcher, and lab records, together with sample-level UDFs."
            ),
            ui.p(
                "Some downstream metadata is not discovered by a single direct join. Instead, sample UDFs store process LUID references such as nd_limsid, qubit_limsid, prep_limsid, seq_limsid, billed_limsid, and extractions_limsid."
            ),
            ui.p(
                "Those UDF-recorded process IDs are resolved back to real process records, and the app then loads process UDFs and artifact UDFs from the linked extraction, quantification, prep, billing, and sequencing steps."
            ),
            ui.p(
                "That is how fields such as Extraction Number, Experiment Name, concentrations, billing values, run-linked filenames, reagent labels, and storage locations are assembled."
            ),
            value="samples",
        ),
        ui.accordion_panel(
            "Sequencing",
            ui.p(
                "Entry point: sequencing step records of the configured sequencing process types."
            ),
            ui.p(
                "From each sequencing step, the app walks upstream through the actual artifact chain, starting from the representative sequencing input artifact and then moving back through the linked Step 7, Step 6, and Step 5 producer processes."
            ),
            ui.p(
                "Process UDFs on the sequencing, Step 7, and Step 6 processes provide run setup and operator-facing fields such as Run ID, read cycles, loading concentration, PhiX percentage, and comment."
            ),
            ui.p(
                "Artifact UDFs on representative and upstream artifacts provide experiment and performance fields such as Experiment Name, application/cassette type, average fragment size, yield, Q30, PF reads, and cluster density."
            ),
            ui.p(
                "Sample context such as species and sample count is recovered by mapping the representative sequencing artifact back to the linked samples."
            ),
            value="sequencing",
        ),
        open=False,
        multiple=True,
    )


def _build_info_modal(formatted_info: dict[str, str], ssl_info: dict[str, str]) -> object:
    """Build the main information modal shown from metadata table views."""
    timestamp_items = [
        ("Projects", formatted_info["projects"]),
        ("Samples", formatted_info["samples"]),
        ("Sequencing", formatted_info["ilmn_sequencing"]),
        ("App Last Refreshed", formatted_info["app_refresh"]),
    ]

    return ui.modal(
        ui.h2("ShinyClarity Information", class_="mb-4"),
        ui.div(
            ui.h3("About"),
            ui.p(
                """This app provides a user-friendly interface to explore and filter LIMS metadata.
                 It connects to the LIMS database and displays information about projects, samples,
                 and sequencing runs."""
            ),
            ui.p(f"App version: {app_version}"),
            ui.h3("Database Information"),
            ui.p(
                "Projects, samples, sequencing runs, and storage boxes are read directly from the live Clarity Postgres database when those views are opened."
            ),
            ui.p(f"Database connection: {ssl_info['connection_security']}"),
            ui.h4("Last Loaded Timestamps"),
            _info_table(timestamp_items),
            ui.h3("Data Fields Collection"),
            ui.p(
                "Source views used by the live metadata queries include sample_udf_view, process_udf_view, artifact_udf_view, and entity_udf_view. The accordion sections below explain which tables and views are used as entry points and where the displayed fields are collected from."
            ),
            _build_data_field_sources_accordion(),
            class_="p-4",
            style="max-height: 70vh; overflow-y: auto;",
        ),
        size="l",
        easy_close=True,
        id="info_modal",
    )


def server(input, output, session):
    """
    Fetch data and wire the single-page dashboard/detail views.
    """
    current_view = reactive.Value("dashboard")
    cache = DatasetCache()

    print(f"[clarity-pg-config] {get_clarity_pg_env_diagnostics()}")
    print(f"[clarity-pg-network] {get_clarity_pg_network_diagnostics()}")

    reagents_server(input, output, session)
    reagent_overview_server(input, output, session)
    storage_server(input)

    projects_controller = projects_server(cache.projects, input)
    samples_controller = samples_server(cache.samples, input)
    seq_controller = seq_server(cache.seq, input)

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

    # ── Navigation ────────────────────────────────────────────────────────
    nav_history = reactive.Value([])  # stack of previously-visited views

    def _navigate(target: str) -> None:
        """Switch views, remembering the prior view so Back returns to it."""
        prev = current_view.get()
        if prev != target:
            nav_history.set(nav_history.get() + [prev])
        current_view.set(target)

    _METADATA_LOADERS = {
        "projects": (cache.load_projects, cache.is_projects_loaded),
        "samples": (cache.load_samples, cache.is_samples_loaded),
        "sequencing": (cache.load_sequencing, cache.is_seq_loaded),
    }

    def _open_metadata_view(view: str) -> None:
        """Navigate to a metadata table view, loading its dataset on first open."""
        _navigate(view)
        loader, is_loaded = _METADATA_LOADERS[view]
        if not is_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message=f"Loading {view}...")
                _run_load_step(view, loader)

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
        _open_metadata_view("projects")

    @reactive.Effect
    @reactive.event(input.open_table_samples)
    def _open_samples():
        _open_metadata_view("samples")

    @reactive.Effect
    @reactive.event(input.open_table_sequencing)
    def _open_sequencing():
        _open_metadata_view("sequencing")

    # Direct switch between metadata tables (from the detail header quick-nav)
    @reactive.Effect
    @reactive.event(input.nav_projects)
    def _nav_projects():
        _open_metadata_view("projects")

    @reactive.Effect
    @reactive.event(input.nav_samples)
    def _nav_samples():
        _open_metadata_view("samples")

    @reactive.Effect
    @reactive.event(input.nav_sequencing)
    def _nav_sequencing():
        _open_metadata_view("sequencing")

    @reactive.Effect
    @reactive.event(input.view_run_samples)
    def _view_samples_for_run():
        """Cross-link: filter the Samples view to the run(s) selected in Sequencing."""
        selection = seq_controller["get_selected_runs"]()
        if not selection:
            ui.notification_show(
                "Select one or more run rows in the table first.",
                type="warning",
                duration=4,
            )
            return

        seq_ids, run_labels = selection
        if not cache.is_samples_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading samples...")
                _run_load_step("samples", cache.load_samples)

        label = ", ".join(dict.fromkeys(run_labels)) if run_labels else None
        samples_controller["set_run_filter"](seq_ids, label)
        _navigate("samples")

    @reactive.Effect
    @reactive.event(input.view_run_projects)
    def _view_projects_for_run():
        """Cross-link: filter the Projects view to projects present in selected runs."""
        selection = seq_controller["get_selected_runs"]()
        if not selection:
            ui.notification_show(
                "Select one or more run rows in the table first.",
                type="warning",
                duration=4,
            )
            return

        seq_ids, run_labels = selection
        if not cache.is_samples_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading samples...")
                _run_load_step("samples", cache.load_samples)

        project_ids = project_limsids_for_seq_limsids(cache.samples(), seq_ids)
        if not project_ids:
            ui.notification_show(
                "No projects were found for the selected run rows.",
                type="warning",
                duration=4,
            )
            return

        if not cache.is_projects_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading projects...")
                _run_load_step("projects", cache.load_projects)

        label = ", ".join(dict.fromkeys(run_labels)) if run_labels else None
        projects_controller["set_project_filter"](project_ids, label)
        _navigate("projects")

    def _selection_label(labels) -> str | None:
        """Build a compact label for a cross-table filter status line."""
        values = list(dict.fromkeys(label for label in labels if label))
        if not values:
            return None
        shown = ", ".join(values[:3])
        remaining = len(values) - 3
        return f"{shown} +{remaining} more" if remaining > 0 else shown

    @reactive.Effect
    @reactive.event(input.view_sample_projects)
    def _view_projects_for_samples():
        """Cross-link: selected Samples -> related Projects."""
        selection = samples_controller["get_selected_sample_links"](
            input.view_sample_projects()
        )
        if not selection:
            ui.notification_show(
                "Select one or more sample rows in the table first.",
                type="warning",
                duration=4,
            )
            return

        project_ids, _seq_ids, sample_labels = selection
        if not project_ids:
            ui.notification_show(
                "No projects were found for the selected sample rows.",
                type="warning",
                duration=4,
            )
            return
        if not cache.is_projects_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading projects...")
                _run_load_step("projects", cache.load_projects)

        projects_controller["set_project_filter"](
            project_ids,
            _selection_label(sample_labels),
            source="sample",
        )
        _navigate("projects")

    @reactive.Effect
    @reactive.event(input.view_sample_runs)
    def _view_runs_for_samples():
        """Cross-link: selected Samples -> related Sequencing runs."""
        selection = samples_controller["get_selected_sample_links"](
            input.view_sample_runs()
        )
        if not selection:
            ui.notification_show(
                "Select one or more sample rows in the table first.",
                type="warning",
                duration=4,
            )
            return

        _project_ids, seq_ids, sample_labels = selection
        if not seq_ids:
            ui.notification_show(
                "No sequencing runs were found for the selected sample rows.",
                type="warning",
                duration=4,
            )
            return
        if not cache.is_seq_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading sequencing runs...")
                _run_load_step("sequencing", cache.load_sequencing)

        seq_controller["set_seq_filter"](
            seq_ids,
            _selection_label(sample_labels),
            source="samples",
        )
        _navigate("sequencing")

    @reactive.Effect
    @reactive.event(input.view_project_samples)
    def _view_samples_for_projects():
        """Cross-link: selected Projects -> related Samples."""
        selection = projects_controller["get_selected_projects"](
            input.view_project_samples()
        )
        if not selection:
            ui.notification_show(
                "Select one or more project rows in the table first.",
                type="warning",
                duration=4,
            )
            return

        project_ids, project_labels = selection
        if not cache.is_samples_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading samples...")
                _run_load_step("samples", cache.load_samples)

        samples_controller["set_project_filter"](
            project_ids,
            _selection_label(project_labels),
        )
        _navigate("samples")

    @reactive.Effect
    @reactive.event(input.view_project_runs)
    def _view_runs_for_projects():
        """Cross-link: selected Projects -> Samples bridge -> Sequencing runs."""
        selection = projects_controller["get_selected_projects"](
            input.view_project_runs()
        )
        if not selection:
            ui.notification_show(
                "Select one or more project rows in the table first.",
                type="warning",
                duration=4,
            )
            return

        project_ids, project_labels = selection
        if not cache.is_samples_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading samples...")
                _run_load_step("samples", cache.load_samples)

        seq_ids = seq_limsids_for_project_limsids(cache.samples(), project_ids)
        if not seq_ids:
            ui.notification_show(
                "No sequencing runs were found for the selected project rows.",
                type="warning",
                duration=4,
            )
            return
        if not cache.is_seq_loaded():
            with ui.Progress(min=1, max=1) as p:
                p.set(message="Loading sequencing runs...")
                _run_load_step("sequencing", cache.load_sequencing)

        seq_controller["set_seq_filter"](
            seq_ids,
            _selection_label(project_labels),
            source="projects",
        )
        _navigate("sequencing")

    # Legacy metadata archive downloads (served from Posit Connect pins)
    def _download_legacy_pin(pin_name: str) -> str:
        from pins import board_connect

        board = board_connect(
            api_key=os.getenv("POSIT_API_KEY"),
            server_url=os.getenv("POSIT_SERVER_URL"),
        )
        return board.pin_download(pin_name)[0]

    @render.download
    def legacy_sample_prep():
        return _download_legacy_pin("vi2172/legacy_metadata_sample_prep")

    @render.download
    def legacy_sequencing_log():
        return _download_legacy_pin("vi2172/legacy_metadata_sequencing_log")

    @reactive.Effect
    @reactive.event(input.open_tool_reagents)
    def _open_reagents():
        _navigate("reagents")

    @reactive.Effect
    @reactive.event(input.open_tool_index_plate_maps)
    def _open_reagent_overview():
        _navigate("reagent_overview")

    @reactive.Effect
    @reactive.event(input.open_tool_storage)
    def _open_storage():
        _navigate("storage")

    @reactive.Effect
    @reactive.event(input.back_to_dashboard)
    def _back_to_dashboard():
        """Return to the previous view (or the dashboard when history is empty)."""
        hist = nav_history.get()
        if hist:
            nav_history.set(hist[:-1])
            current_view.set(hist[-1])
        else:
            current_view.set("dashboard")

    @reactive.Effect
    @reactive.event(input.go_home)
    def _go_home():
        """Always return to the dashboard front page and reset navigation history."""
        nav_history.set([])
        current_view.set("dashboard")

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

        if current_view.get() in metadata_table_views:
            active = current_view.get()
            metadata_switcher = ui.div(
                *[
                    ui.input_action_button(
                        f"nav_{view}",
                        label,
                        class_=(
                            "btn btn-sm "
                            + ("btn-primary" if view == active else "btn-outline-primary")
                        ),
                    )
                    for view, label in (
                        ("projects", "Projects"),
                        ("samples", "Samples"),
                        ("sequencing", "Sequencing"),
                    )
                ],
                class_="btn-group btn-group-sm detail-view-switcher",
                role="group",
                aria_label="Switch metadata table",
            )
            toolbar_children.extend(
                [
                    metadata_switcher,
                    ui.input_action_button(
                        "go_home",
                        ui.TagList(icon_svg("house"), " Home"),
                        class_="btn btn-outline-primary btn-sm detail-home-button",
                    ),
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
        ssl_info = _format_ssl_modal_info()
        ui.modal_show(_build_info_modal(formatted_info, ssl_info))

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
