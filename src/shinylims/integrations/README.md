# Integrations

This package connects ShinyLIMS to three external systems. Each uses a
different protocol and serves a different purpose.

## External systems

| System | Protocol | Modules | Purpose |
|--------|----------|---------|---------|
| Clarity Postgres | SQLAlchemy (psycopg) | `clarity_pg.py`, `clarity_models.py`, `queries/` | Read-only dashboard data |
| Clarity REST API | HTTPS + XML | `lims_api.py` | Reagent lot management, inventory, sequencing planner |
| SAGA cluster | SSH / SFTP | `ssh_transport.py`, `upload_atlas_file_to_saga.py` | ATLAS CSV upload with 2FA |

## Data flow

```
Shiny UI (features/)
    |
data_utils.py            -- fetch + transform, returns (DataFrame, timestamp)
    |
    +-- queries/*.py     -- build_*_rows() returns list[dict]
    |       |
    |   clarity_pg.py    -- SQLAlchemy session / connection pool
    |       |
    |   clarity_models.py -- ORM models for the Clarity Postgres schema
    |       |
    |   Clarity Postgres database (read-only)
    |
    +-- lims_api.py      -- REST XML client (reagent lots, planner, index plates)
    |       |
    |   Clarity REST API (/api/v2)
    |
    +-- upload_atlas_file_to_saga.py
            |
        ssh_transport.py -- SSH transport, host-key validation, 2FA auth
            |
        SAGA login nodes (login.saga.sigma2.no)
```

## Why two Clarity access paths?

- **Postgres** is used for the dashboard tables (projects, samples,
  sequencing, storage). It is fast, read-only, and avoids the REST API's
  pagination and XML overhead.
- **REST API** is used for write operations (creating reagent lots) and for
  data that is only accessible through the API (reagent kit inventory, planner
  snapshots, index plate notes).

## Artifact lineage traversal (DAG walking)

Clarity stores lab workflow as a directed acyclic graph (DAG): samples enter
processes that produce artifacts, which feed into further processes. The
queries in `queries/samples.py` and `queries/sequencing.py` walk this graph
backwards -- from a sequencing run back to the original sample -- to collect
measurements and process IDs at each step.

The traversal uses `OutputMapping` and `ProcessIOTracker` to follow
artifact-to-process links, and bulk-loads all needed UDFs upfront (via
`_load_process_udfs` / `_load_artifact_udfs` in `queries/_shared.py`) to
avoid N+1 query problems.

## queries/ subpackage

Each module builds rows for one dashboard table:

| Module | Function | What it returns |
|--------|----------|-----------------|
| `projects.py` | `build_project_rows()` | Projects with sample counts, species, submitter |
| `samples.py` | `build_sample_rows()` | Samples with full lineage, QC measurements, storage location |
| `sequencing.py` | `build_sequencing_run_rows()` | Sequencing runs with yield, quality, and run metadata |
| `storage.py` | `build_storage_container_rows()` | DNA storage box status |

Shared constants and helpers live in `_shared.py` (excluded project IDs,
container state labels, UDF bulk-loaders, operator lookup).

## SAGA upload

The upload pipeline in `upload_atlas_file_to_saga.py`:

1. Validates CSV structure (required columns: "Sample Name", "NIRD Filename")
2. Validates credentials (username format, TOTP format, password presence)
3. Connects via SSH to a SAGA login node
4. Verifies the host key against `~/.ssh/known_hosts` (strict, no auto-add)
5. Authenticates with keyboard-interactive 2FA (password + TOTP)
6. Creates the remote directory if missing
7. Uploads via SFTP

## Environment variables

All external connections are configured through environment variables.
See `.env.example` in the project root for the full list. Key groups:

- **Postgres**: `CLARITY_PG_HOST`, `CLARITY_PG_PORT`, `CLARITY_PG_DB`,
  `CLARITY_PG_USER`, `CLARITY_PG_PASSWORD`, plus optional SSL vars
- **REST API**: `LIMS_BASE_URL`, `LIMS_API_USER`, `LIMS_API_PASS`
- **Sequencing filter**: `CLARITY_PG_SEQUENCING_TYPE_IDS` (comma-separated
  process type IDs that identify sequencing processes)
- **Performance**: `CLARITY_PG_TIMING_ENABLED` (optional query timing logs)
