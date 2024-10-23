### Shinylims

A Python Shiny app for LIMS reporting hosted on Posit Connect.
This python package is managed with uv (https://docs.astral.sh/uv). To run it, clone the repository and install the package with:

```
uv sync
```

Then, run the shiny app with:

```
uv run uvicorn shinylims.app:app
```

For development:

* Set the deploy mode in deploy_mode.yaml. If set to 'test', any pushes to main will be deployed to the test-deploy shiny app instance on posit connect. Else set the mode to 'prod' to deploy on the production instance or 'both' to update both instances. The idea here is to first implement changes on an instance running on ypu local computer. When confirmed running as expected locally, first push to the test posit instance to confirm that everything also functions on posit. Then change to 'prod' and push again to implement changes to the production instance of the app.
* For local development, the apikey and posit connect url must be provided in a .env file.
* When pushing to main a Github actions pipeline will ensure that manifest and requirement files are created for posit deployment. These files along with any updates to the code are forced pushed to either the production deploy branch or the test_deploy branch depending on the mode set (see above)