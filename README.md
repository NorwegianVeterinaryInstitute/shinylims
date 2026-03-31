# Shinylims

A Python Shiny app for LIMS reporting hosted on Posit Connect.

The app displays live metadata read from the Clarity Postgres database.

This python package requires Python 3.12+ and is managed with [uv](https://docs.astral.sh/uv). To run it, clone the repository and install the package with:

```
uv sync
```

Then, run the shiny app with:

```
uv run uvicorn shinylims.app:app
```

Pushes to `main` are automatically processed by the deployment workflow and can update the Posit Connect deploy branches. There are two instances running: one test instance with admin-only access and one main production instance where access can be granted on request. Each instance is associated with its own git deploy branch. The value in `deploy_mode.txt` specifies which deploy branch should be updated.

| Posit instance name | Git deploy branch name | Value for deploy_mode.txt | Access |
| ------------------- | ---------------------  | ------------------------- | ------ |
| shinylims-uv-test-deploy | test_deploy | test | admin access only | 
| shinylims-uv-deploy | deploy | prod | open for everyone by request |
| both of the above  | both of the above | both | - |


Recommended development flow:

1. Create a new branch from `main` for each feature or fix, for example `feature/my-change`.
2. Run and verify the app locally first.
3. If you want GitHub Actions to deploy from that feature branch, add the branch name to the `on.push.branches` list in `.github/workflows/deploy.yml`. Feature branches are not deployed unless they are explicitly listed there.
4. Keep `deploy_mode.txt` set to `test` while working on a feature branch. If that branch is listed in `.github/workflows/deploy.yml`, pushing with `prod` would deploy to the production Posit app before the branch is merged.
5. Push the feature branch to update the test Posit instance, then verify the change there.
6. After verification, open a PR and merge the branch into `main`.
7. Only switch `deploy_mode.txt` to `prod` on the branch or commit that is intended to go to `main` for production deployment.
8. Use `both` only when you intentionally want to update both deploy branches in the same run.

For doing code development locally, the api-key and Posit Connect URL must be provided in an .env file. Variables for the credentials are named `POSIT_API_KEY` and `POSIT_SERVER_URL`.

The deployment is handled by the GitHub Actions workflow stored in `.github/workflows/deploy.yml`. That workflow generates the manifest and `requirements.txt` file used for Posit deployment.

Automated dependency updates are configured with Dependabot in `.github/dependabot.yml` for both `uv` dependencies and GitHub Actions workflows.

## Lab Tools

The **Lab Tools** tab contains LIMS-integrated features that require Clarity credentials (see secrets section below):

- `Reagent Lot Registration`: create and submit reagent lots to Clarity LIMS.
- `Reagent Overview`: review prep sets, sequencing stock, and index plate usage together.
- `Storage Box Status`: view populated/discarded DNA for NGS storage containers.

## LIMS-backed tool security and secrets

The LIMS-backed lab tools read Clarity credentials only from environment variables:

- `LIMS_BASE_URL`
- `LIMS_API_USER`
- `LIMS_API_PASS`

Local development can use a `.env` file (loaded automatically when `python-dotenv` is available).
See [.env.example](.env.example).

On Posit Connect, configure these values in **Vars / Secrets** for the content item instead of using `.env`.

For direct Clarity Postgres access, SSL can be configured with:

- `CLARITY_PG_SSLMODE` such as `prefer`, `require`, `verify-ca`, or `verify-full`
- `CLARITY_PG_SSLROOTCERT`, `CLARITY_PG_SSLCERT`, and `CLARITY_PG_SSLKEY` when certificate validation or client certificates are required

If you use `CLARITY_PG_URL`, include SSL parameters directly in that URL, for example `?sslmode=require`.

Authorization for `Reagent Lot Registration` and `Reagent Overview`:
- Authorization is configured in `src/shinylims/security.py`:
  - `CONNECT_ALLOWED_GROUP` (required Connect group)
  - `CONNECT_ALLOWED_USERS` (optional individual usernames)
  - `LOCAL_DEV_ALLOW_ALL` for local development behavior

## Maintaining Reagents Tool Configuration

The reagent register is defined in a config module:

- `src/shinylims/config/reagents.py`

Edit only `REAGENT_DEFINITIONS` in that file. Each entry has:

- `type_name`: Reagent type name used in UI and LIMS logic.
- `kit_id`: Clarity reagent kit ID (digits only).
- `naming_group`: One of `prep`, `index`, `miseq`, `phix`.
- `requires_rgt_number`: `True` if RGT scan is required.
- `requires_miseq_kit_type`: `True` if MiSeq kit type is required.
- `variants`: scanner/select options for that type.

Each variant supports:

- `ref`: scanned barcode / selector value.
- `label`: dropdown text shown in UI.
- `set_letter`: required for index variants.
- `miseq_kit_type`: required when `requires_miseq_kit_type=True`.

Common maintenance tasks:

1. Change ref barcode or display label: update the relevant `variants` item only.
2. Change LIMS kit mapping: update `kit_id` for that reagent type.
3. Add a new reagent type: add one new entry with metadata + variants.

If a new reagent needs a new `naming_group`, more than config changes are required. You must update `src/shinylims/config/reagents.py` to allow the new group and update the reagent tool logic in `src/shinylims/features/reagents/domain.py` so internal naming, sequencing, and submission behavior handle that group correctly.

The module validates configuration at import and fails early on issues (duplicate type names, duplicate refs, invalid naming group, missing required fields, etc.).

Derived exports used by the app are generated automatically (`REAGENT_TYPES`, `SCANNABLE_REAGENTS`, `PREP_REAGENT_TYPES`, `REAGENT_KIT_IDS`, selector maps), so the reagent feature code under `src/shinylims/features/reagents/` and `integrations/lims_api.py` should not be edited for reagent list changes.

- `PREP_REAGENT_TYPES` is generated automatically from `REAGENT_TYPES` where `naming_group == "prep"`.
- Prep reagents are currently submitted with LIMS status `PENDING` in the tool logic.
