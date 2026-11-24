# Sentinel-2 preprocessing Conductor worker

The worker polls Conductor for `preprocess_sentinel2` tasks. Each task processes
all `*.zip` files in `../eodag/downloads` and writes GeoTIFF outputs to `output`.
The worker runs the preprocessing code in its own container using the same image;
it does not need access to the Docker socket.

## Start the worker

From the `src` directory (where `docker-compose.yaml` is located), start the
worker with:

```powershell
docker compose --profile conductor up -d --build conductor_worker
```

By default, the worker connects to `http://host.docker.internal:8080/api`.
Override the address or task type with environment variables before starting:

```powershell
$env:CONDUCTOR_SERVER_URL = "http://host.docker.internal:8080/api"
$env:CONDUCTOR_TASK_TYPE = "preprocess_sentinel2"
docker compose --profile conductor up -d --build conductor_worker
```

The `conductor_worker` service mounts the input ZIP directory read-only and
shares the `extracted` and `output` directories with the host. A task fails if
the input directory contains no ZIP archives or if preprocessing raises an
error. Successful task output contains `output_count` and `output_files`.

## Register definitions

Register the task definition and workflow in the Conductor API:

```powershell
$base = "http://localhost:8080/api"
$taskDefinition = Get-Content ".\conductor_definitions\task_definition.json" -Raw
$taskDefinitionObject = ConvertFrom-Json $taskDefinition
$taskDefinitions = ConvertTo-Json -InputObject @($taskDefinitionObject) -Depth 10
Invoke-RestMethod "$base/metadata/taskdefs" -Method POST `
  -ContentType "application/json" -Body $taskDefinitions

$workflowDefinition = Get-Content ".\conductor_definitions\preprocess_sentinel2_workflow.json" -Raw
Invoke-RestMethod "$base/metadata/workflow" -Method Put `
  -ContentType "application/json" -Body $workflowDefinition
```

Start a run with an empty input object:

```powershell
Invoke-RestMethod "http://localhost:8080/api/workflow/preprocess_sentinel2_workflow?version=1" `
  -Method Post -ContentType "application/json" -Body "{}"
```
