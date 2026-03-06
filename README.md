### Shinylims

A Python Shiny app for LIMS reporting hosted on Posit Connect.

The app displays metadata stored in a SQLite pin. The db upserts and subsequent pinning to Posit Connect is done using scripts running on the Illumina LIMS Clarity server:
https://github.com/NorwegianVeterinaryInstitute/nvi_lims_epps/tree/main/shiny_app 

This python package is managed with uv (https://docs.astral.sh/uv). To run it, clone the repository and install the package with:

```
uv sync
```

Then, run the shiny app with:

```
uv run uvicorn shinylims.app:app
```

Any pushes to main is automatically deployed on Posit Connect. Here we have two instances running; one test instance with admin-only access and one main production instance where everyone can gain access if needed. Each instance is associated with its own deploybranch on git. The value given in ```deploy_mode.txt``` specifies which deploy branch you are working on.

| Posit instance name | Git deploy branch name | Value for deploy_mode.txt | Access |
| ------------------- | ---------------------  | ------------------------- | ------ |
| shinylims-uv-test-deploy | test-deploy | test | admin access only | 
| shinylims-uv-deploy | deploy | prod | open for everyone by request |
| both of the above  | both of the above | both | - |


The idea here is to first implement any changes on an instance running on your local computer. After confirmed running as expected locally, push to the test Posit instance to confirm that everything also functions on Posit. Then change mode to 'prod' and push again to implement changes to the production instance of the app. You can also choose to deploy from both branches at the same time by using the mode ```both```.

For doing code development locally, the api-key and Posit Connect URL must be provided in an .env file. Variables for the credentials are named ```POSIT_API_KEY``` and ```POSIT_SERVER_URL```.

The deployment is handled by the github actions workflow stored in .github\workflows\deploy.yml. This action will create the manifest and requirement files for posit deployment.

## Reagents security and secrets

The Reagents tool reads LIMS credentials only from environment variables:

- `LIMS_BASE_URL`
- `LIMS_API_USER`
- `LIMS_API_PASS`

Local development can use a `.env` file (loaded automatically when `python-dotenv` is available).
See .env.example file.

On Posit Connect, configure these values in **Vars / Secrets** for the content item instead of using `.env`.

Reagents authorization:
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

The module validates configuration at import and fails early on issues (duplicate type names, duplicate refs, invalid naming group, missing required fields, etc.).

Derived exports used by the app are generated automatically (`REAGENT_TYPES`, `SCANNABLE_REAGENTS`, `PREP_REAGENT_TYPES`, `REAGENT_KIT_IDS`, selector maps), so `tables/reagents.py` and `integrations/lims_api.py` should not be edited for reagent list changes.

- `PREP_REAGENT_TYPES` is generated automatically from `REAGENT_TYPES` where `naming_group == "prep"`.
- Prep reagents are currently submitted with LIMS status `PENDING` in the tool logic.
