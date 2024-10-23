### Shinylims

A Python Shiny app for LIMS reporting hosted on Posit Connect.

The app displays metadata stored in pins. The pinning of data to Posit Connect is done using scripts running on the Illumina LIMS Clarity server:
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


The idea here is to first implement any changes on an instance running on your local computer. After confirmed running as expected locally, push to the test Posit instance to confirm that everything also functions on Posit. Then change mode to 'prod' and push again to implement changes to the production instance of the app. You can also choose to deploy from both branches at the same time by using the mode ```both```.

For doing code development locally, the api-key and Posit Connect URL must be provided in an .env file. Variables for the credentials are named ```POSIT_API_KEY``` and ```POSIT_SERVER_URL```.

The deployment is handled by the github actions workflow stored in .github\workflows\deploy.yml. This action will create the manifest and requirement files for posit deployment.