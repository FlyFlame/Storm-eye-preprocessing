# Sentinel-2 preprocessing Conductor worker

The worker polls Conductor for `preprocess_sentinel2` tasks. Each task processes
all `*.zip` files in the configured input directory. The worker runs the
preprocessing code in its own container using the same image; it does not need
access to the Docker socket.

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

## Task parameters

All parameters are optional. If omitted or set to `null`, the worker uses the
corresponding value from `config.py`.

| Workflow input | Type | Default |
| --- | --- | --- |
| `workspace_dir` | string | `/app` |
| `input_zip_dir` | string | `/app/eodag/downloads` |
| `extract_dir` | string | `/app/src/extracted` |
| `output_dir` | string | `/app/src/output` |
| `bands` | array of strings | `["B02", "B03", "B04", "B08"]` |
| `include_20m_bands` | boolean | `true` |
| `bands_20m` | array of strings | `["B05", "B06", "B07", "B8A", "B11", "B12"]` |
| `target_resolution_m` | positive number | `10` |
| `scale_factor` | positive number | `10000` |
| `delete_extracted_bands_after_merge` | boolean | `true` |

Directory values are paths inside the worker container. They must refer to
mounted directories; the input mount is read-only, while extraction and output
mounts are writable. If `workspace_dir` is changed without specifying
`input_zip_dir`, the input directory defaults to `<workspace_dir>/eodag/downloads`.
When `delete_extracted_bands_after_merge` is `false`, the extracted JP2 bands
remain in a per-archive subdirectory under `extract_dir`. For example, submit
custom bands, resolution, and retention choice as workflow input:

```powershell
$body = @{
  bands = @("B04", "B08")
  include_20m_bands = $false
  target_resolution_m = 20
  scale_factor = 10000
  delete_extracted_bands_after_merge = $false
} | ConvertTo-Json -Depth 10

Invoke-RestMethod "http://localhost:8080/api/workflow/preprocess_sentinel2_workflow?version=1" `
  -Method Post -ContentType "application/json" -Body $body
```

Unknown task inputs and values with the wrong type or non-positive numeric
settings are rejected as task failures.

## Register definitions

Register the task definition and workflow in the Conductor API:

```powershell
$base = "http://localhost:8080/api"
$taskDefinition = Get-Content ".\conductor_definitions\task_definition.json" -Raw
$taskDefinitionObject = ConvertFrom-Json $taskDefinition
$taskDefinitions = ConvertTo-Json -InputObject @($taskDefinitionObject) -Depth 10
Invoke-RestMethod "$base/metadata/taskdefs" -Method POST `
  -ContentType "application/json" -Body $taskDefinitions

# If the task definition already exists, update it with PUT and a single object:
# Invoke-RestMethod "$base/metadata/taskdefs" -Method PUT `
#   -ContentType "application/json" -Body $taskDefinition

$workflowDefinition = Get-Content ".\conductor_definitions\preprocess_sentinel2_workflow.json" -Raw
Invoke-RestMethod "$base/metadata/workflow" -Method Put `
  -ContentType "application/json" -Body $workflowDefinition
```

Start a run with an empty input object:

```powershell
Invoke-RestMethod "http://localhost:8080/api/workflow/preprocess_sentinel2_workflow?version=1" `
  -Method Post -ContentType "application/json" -Body "{}"
```
