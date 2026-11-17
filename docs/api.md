# Sentinel API

Base URL: `http://127.0.0.1:8000`. [Interactive Swagger UI](http://127.0.0.1:8000/docs) · [exported OpenAPI](openapi.json) · [dashboard](http://127.0.0.1:8000/). All endpoints below use JSON. The dashboard and API share an origin; polling reads the coordinator's authoritative state. No authentication is configured. Use one process bound to loopback.

| Method and path | Request | Success |
|---|---|---|
| GET /api/health | — | Backend status, runtime_ready, data_ready, data_error and profile. Readiness checks the prepared file digests on service startup. |
| GET /api/state | — | devices, profile, minimum, online count, ready and latest run (null before any run). |
| GET /api/devices | — | Device array: id, name, original device, partition_sha256, split counts, online, eligible, activity, generation and last participation. |
| PUT /api/devices/{cid}/power | `{"online":true}` | id and online. Repetition preserves the same power state and lease generation. |
| GET /api/threshold | — | `{"minimum":3}` for the three-required setup. |
| PUT /api/threshold | `{"minimum":3}` | Updated minimum; 1 through configured device count inclusive. Takes effect at the next dispatch. |
| POST /api/runs | Config object; `{}` uses defaults | 201, `{"id":"<run-id>"}`. Work continues in the background. |
| GET /api/runs | — | Newest first: id, started, status, completed. |
| GET /api/runs/{rid} | — | Full run snapshot, configuration, cohort, attempts, committed models, majority baseline and final test. |
| POST /api/runs/{rid}/stop | No body | id and command. Stop is asynchronous; poll until stopped. |
| POST /api/runs/{rid}/continue | No body | Release a review boundary. If the next round lacks quorum, its state becomes waiting. |
| GET /api/runs/{rid}/rounds/{number} | — | One measured model result; number 0 is the baseline. Includes checkpoint, version, validation and confusion counts. |

**Start settings:** `rounds` 1–100 (default 3), `epochs` 1–20 (1), `batch` 1–4096 (64), `lr` greater than 0 and at most 1 (0.001), `seed` 0–2147483647 (42), `review` boolean (false through the API; the dashboard initially checks this option). Review holds after each non-final trained round. Training thresholds and power states persist across runs. Target rounds and model settings are fixed at start.

**Errors:** 404 for an unknown client, run, or uncommitted round; 409 for a duplicate start, unavailable data, invalid run command or continue outside review; 422 for invalid thresholds, unexpected fields, wrong types or out-of-range settings. Business errors use `{"detail":"explanation"}`. Request schema errors carry FastAPI's array of field errors. Inspect `run.error` for failures after a successful asynchronous start.

## Worked example: release a waiting run

Start with the three-device demo and no active run. From a second PowerShell terminal:

```powershell
$base = 'http://127.0.0.1:8000/api'
function Set-SentinelPower($id, [bool]$on) {
    Invoke-RestMethod -Method Put -Uri "$base/devices/$id/power" -ContentType 'application/json' -Body (@{online=$on} | ConvertTo-Json)
}
Invoke-RestMethod -Method Put -Uri "$base/threshold" -ContentType 'application/json' -Body '{"minimum":3}'
Set-SentinelPower 1 $true
Set-SentinelPower 2 $true
Set-SentinelPower 3 $false
$run = Invoke-RestMethod -Method Post -Uri "$base/runs" -ContentType 'application/json' -Body '{"rounds":2,"review":true}'
$uri = "$base/runs/$($run.id)"
do { Start-Sleep -Milliseconds 200; $r = Invoke-RestMethod $uri } while ($r.status -in 'initializing','evaluating')
$r | Select-Object id,status,completed
Set-SentinelPower 3 $true
do { Start-Sleep -Milliseconds 200; $r = Invoke-RestMethod $uri } until ($r.status -in 'review','failed','stopped')
(Invoke-RestMethod "$uri/rounds/1").validation.pooled
Set-SentinelPower 3 $false
Invoke-RestMethod -Method Post -Uri "$uri/continue"
Invoke-RestMethod "$base/state" | Select-Object online,minimum
Set-SentinelPower 3 $true
```

The first poll settles at `waiting`, `completed:0`; the third power-on wakes Flower. After the review boundary and power-off the state has `online:2, minimum:3`; restoring the device finishes round 2. The executable cross-platform version, `python -m scripts.smoke`, asserts those transitions, duplicate-start rejection, idempotence, invalid threshold rejection and measured round consistency.

## Read one result

Use [the verified browser run's Round 1](http://127.0.0.1:8000/api/runs/cc9680438496/rounds/1) on the supplied running instance; a fresh checkout generates its own run IDs. Each round response includes:

- `number`, `status` (baseline or committed), UTC `ended`, `duration` in seconds, `participants`, unique-local-example count `examples`, `training_loss`, checkpoint path, SHA-256 `version` and parameter-change L2 norm `delta`.
- `validation.pooled`: tn, fp, fn, tp, benign, attack, n, accuracy, loss, precision, recall, f1. Ratios are fractions; timestamps are ISO 8601. Null ratios have a zero denominator. Mean loss is weighted by evaluated examples. Baseline training loss is null.
- `validation.clients`: the same measurements keyed by evaluator ID. `expected`, `evaluated`, `coverage` and `errors` identify full, partial or missing evaluation. Fixed evaluation includes offline training clients on this host.
- In the parent run, `attempts` records attempt ID, target round, selected IDs, dispatch minimum, input version, accepted local example counts, dropped IDs, errors, timestamps and outcome as they become known. Only committed attempts increment `completed`. `test` carries a separate final evaluation and producing version after all target rounds.

An active run can be initializing, waiting, training, evaluating, between rounds, review or stopping. Terminal states are completed, stopped, interrupted and failed. A requested stop is acknowledged before the worker exits. Refreshing the page does not mutate a run. `GET /openapi.json` serves the live schema; the export was checked against the final service.
