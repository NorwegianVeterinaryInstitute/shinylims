### Shinylims

A Python Shiny app for LIMS reporting.
This python package is managed with uv (https://docs.astral.sh/uv). To run it, clone the repository and install the package with:

```
uv sync
```

Then, run the shiny app with:

```
uv run uvicorn shinylims.app:app
```

Remember to update the manifest before making commits

```
uvx --from rsconnect-python --python .venv/Scripts/python.exe rsconnect write-manifest shiny . --overwrite --entrypoint shinylims.app:app
```


Environment setup:

```
python -m venv pyshiny-env
cd pyshiny-env
source bin/activate
pip install -r requirements.txt
```

Then clone the repo, and open the app.

Runs locally with:

```
shiny run app.py
```

Remember to update the manifest before making commits

```
rsconnect write-manifest shiny . --overwrite
```