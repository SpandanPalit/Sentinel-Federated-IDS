<h1 align="center">Sentinel Federated IDS</h1>
<p align="center"><strong>A Decentralized Privacy Preserving Federated Deep-Learning Framework for Intelligent Intrusion Detection in Heterogeneous IoT Networks</strong></p>
<p align="center">By <a href="https://github.com/SpandanPalit">Spandan Palit</a></p>
<p align="center"><a href="https://flower.ai/"><img src="https://img.shields.io/badge/Flower-1.43-38745b" alt="Flower 1.43"></a> <a href="https://pytorch.org/"><img src="https://img.shields.io/badge/PyTorch-CPU-b05132" alt="PyTorch CPU"></a> <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.138-29796d" alt="FastAPI"></a> <a href="https://sqlite.org/"><img src="https://img.shields.io/badge/SQLite-local-46627c" alt="SQLite"></a> <a href="https://react.dev/"><img src="https://img.shields.io/badge/React-TypeScript-466e89" alt="React and TypeScript"></a></p>
<p align="center"><a href="#run-locally">Local setup</a> · <a href="#api-requests">API requests</a> · <a href="#development-roadmap">Roadmap</a> · <a href="docs/verification.md">Verification</a></p>

![Sentinel's fleet console after two measured training rounds](docs/dashboard.jpg)

## About

<p align="justify">Turn a device on in the fleet to make its local training partition eligible for the next Flower round. Sentinel runs three simulated IoT clients on one computer. Each owns real N-BaIoT records; the console exposes the participants, sample weights, checkpoint and evaluation behind each displayed result. This is a local experiment on captured traffic. Live network monitoring and physical device control are outside its scope.</p>

## Technology stack

| Component | Technology | Role in one training round |
|---|---|---|
| Fleet console | React · TypeScript · Vite | Sends device power commands and displays the latest committed round. |
| Control service | FastAPI · Uvicorn | Validates commands and wakes the training coordinator when enough clients are online. |
| Federation | Flower · FedAvg | Sends global weights to eligible clients and averages their updates by local sample count. |
| Local model | PyTorch · CPU | Trains a 115-input MLP on one device partition and evaluates the global model locally. |
| Preparation and storage | NumPy · SQLite | NumPy holds device partitions and checkpoints. SQLite stores run settings, attempts and measured results. |

## Run locally

<p align="justify">Tested on Windows with 64-bit <strong>Python 3.14.7</strong>, <strong>Node 24.21.0</strong>, npm 11.19.0, Flower 1.43.0, PyTorch 2.15.0+cpu, FastAPI 0.138.2, React 18.3.1, TypeScript 5.7.3 and Vite 6.4.1. Use one Uvicorn process. Download the dependencies and original dataset once; the demonstration, including Swagger and the data preparation step, runs offline thereafter.</p>

<p align="justify"><strong>One-time dataset setup.</strong> Clone the project, then download the original N-BaIoT archive from <a href="https://doi.org/10.24432/C5RC8J">UCI</a>. Extract the ZIP and the attack RAR archives for Danmini Doorbell, Ecobee Thermostat and Ennio Doorbell. Put their device directories directly under <code>data/raw/</code> with each device's benign CSV and extracted attack CSVs in the layout shown in the <a href="docs/data.md">data guide</a>.</p>

```sh
git clone https://github.com/SpandanPalit/Sentinel-Federated-IDS.git
cd Sentinel-Federated-IDS
```

<p align="justify">The preparation command below selects the demo records from those CSVs and writes one partition per device under <code>state/prepared/</code>. Run it once per computer. Later launches reuse those partitions. For an existing dataset elsewhere, substitute <code>--raw "path/to/device-directories"</code>.</p>

<p align="justify">From the checkout root in PowerShell (no activation or execution policy change needed):</p>

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci --prefix frontend
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m sentinel.prepare --raw "data/raw"
.\.venv\Scripts\python.exe -m uvicorn sentinel.api:app --host 127.0.0.1 --port 8000
```

<p align="justify">Bash equivalents:</p>

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm ci --prefix frontend
npm --prefix frontend run build
python -m sentinel.prepare --raw "data/raw"
python -m uvicorn sentinel.api:app --host 127.0.0.1 --port 8000
```

<p align="justify">Open the <a href="http://127.0.0.1:8000/">dashboard</a> or <a href="http://127.0.0.1:8000/docs">interactive Swagger UI</a>. Read the <a href="docs/api.md">API guide</a> or <a href="docs/openapi.json">exported OpenAPI schema</a>. To shut down, stop an active run in the console, then press <strong>Ctrl+C</strong> in the server terminal. Restart with the last command. No account, API key, GPU or Docker installation is needed.</p>

## Try one training round

1. Set **Minimum online** to **3** and **Target rounds** to **2**. Leave **Review between rounds** checked. Power on Client 1 and Client 2; leave Client 3 offline.
2. Select **Start run**. Round 0 evaluates the initial model on all three fixed validation partitions. After initialization the console reads **Waiting for 1 more client · 2 of 3 required online**, with **0 / 2** completed.
3. Power on Client 3. Flower sends the same global parameters to all three trainers, receives their updates, and commits Round 1. Inspect **R1** in history, expand **Confusion matrix & per-client results**, and compare the checkpoint identifier with the round API.
4. At the review boundary, turn Client 3 off, then click **Continue to next round**. Even after refreshing, Round 1 remains available while training waits. Restore Client 3 to complete Round 2 automatically. The final reserved-test result is under `test` in the run API. Disable review for unattended continuous training.

## API requests

| Method | Path | Operation |
|---|---|---|
| GET | `/api/health`, `/api/state`, `/api/devices` | Check readiness, inspect the dashboard snapshot or list device activity. |
| PUT | `/api/devices/{cid}/power` | Set training eligibility with `{"online":true}` or `{"online":false}`. |
| GET / PUT | `/api/threshold` | Read the quorum or set it with `{"minimum":3}`. |
| GET / POST | `/api/runs` | List runs or start one with `{"rounds":2,"review":true}`. A successful start returns a run ID. |
| GET | `/api/runs/{rid}` | Inspect run status, attempts and completed models. |
| GET | `/api/runs/{rid}/rounds/{number}` | Retrieve a checkpoint identifier, participants and validation measurements. |
| POST | `/api/runs/{rid}/continue`, `/api/runs/{rid}/stop` | Release a review boundary or request a clean stop. |

<p align="justify">With Sentinel waiting for its third client, run these requests in PowerShell. The first powers on Client 3. The second reads the resulting run state.</p>

```powershell
$api = 'http://127.0.0.1:8000/api'
Invoke-RestMethod -Method Put -Uri "$api/devices/3/power" -ContentType 'application/json' -Body '{"online":true}'
(Invoke-RestMethod "$api/state").run | Select-Object id,status,completed
```

## Architecture

```mermaid
flowchart TD
 UI["Sentinel fleet console"] -->|HTTP power, threshold, run commands| API["FastAPI"]
 API -->|wake / update eligibility| CO["Coordinator · worker thread"]
 CO -->|select eligible clients| FL["Flower Server + FedAvg"]
 FL -->|global weights| A["Client 1 · Danmini"]
 FL -->|global weights| B["Client 2 · Ecobee"]
 FL -->|global weights| C["Client 3 · Ennio"]
 A -->|local weights + sample count| FL
 B -->|local weights + sample count| FL
 C -->|local weights + sample count| FL
 FL -->|aggregated weights| CO
 CO -->|global weights| EV["Fixed local evaluators · same 3 partitions"]
 EV -->|confusion counts + loss| CO
 CO -->|commit results| DB[("SQLite + checkpoints")]
 API -->|read recorded state| DB
 API -->|poll responses| UI
```

<p align="justify">The local transport adapts Flower <code>ClientProxy</code> to a <code>NumPyClient.to_client()</code> instance per partition. Flower's <code>Server.fit_round</code> dispatches FitIns messages, collects FitRes messages and calls the strategy. The subclass gates selection and eligible replies, then calls Flower's own FedAvg aggregation. All clients run in-process; dispatch is limited to one worker on this CPU demo. PyTorch trains a 115 → 64 → 32 → 2 MLP with hidden ReLUs, two raw logits, integer class labels and cross-entropy. Prediction uses argmax. Demo defaults: Adam, learning rate 0.001, batch 64, one epoch, seed 42. The API accepts all of these training settings except optimizer choice.</p>

<p align="justify">For one parameter, values <strong>0.2</strong> and <strong>0.8</strong> from clients with <strong>100</strong> and <strong>300</strong> local records yield <strong>(100 × 0.2 + 300 × 0.8) / 400 = 0.65</strong>. Flower applies that operation to each corresponding weight and bias. Training multiple epochs does not multiply a client's weight.</p>

<p align="justify">All online trainers are selected at dispatch. The persisted attempt freezes the quorum and selection. A power transition invalidates that training lease, even if the client is quickly powered back on. Each local batch checks the lease; a final reply check excludes disconnected clients. The same minimum must be met by accepted replies. An insufficient attempt keeps the prior model, records failures, and retries the same round number. Availability changes after the acceptance boundary apply to future dispatches. A stop cancels uncommitted work; restarting the service marks a previously active run interrupted and retains committed checkpoints.</p>

## Data and measured results

<p align="justify">The locally prepared <strong>demo</strong> profile contains a small, attributed subset of <a href="https://doi.org/10.24432/C5RC8J">N-BaIoT from UCI</a>. <a href="docs/data.md">Data preparation and provenance</a> covers local source directories, manual extraction, offline reproduction, the exact column order and inference. Use <code>python -m sentinel.prepare --raw "data/raw"</code> to prepare from extracted originals. Separate attack CSVs are assigned as groups. Single ordered benign captures use contiguous blocks separated by 128 observations in this profile. Each device fits its own scaler on training rows only. A global, pre-scaling duplicate audit removed 8 validation and 14 test rows matching earlier splits.</p>

| Client | Device | Training | Validation | Reserved test |
|---|---|---:|---:|---:|
| 1 | Danmini Doorbell | 2,560 | 768 | 768 |
| 2 | Ecobee Thermostat | 2,560 | 768 | 768 |
| 3 | Ennio Doorbell | 1,792 | 504 | 498 |
| **Total** | | **6,912** | **2,040** | **2,034** |

<p align="justify"><strong>Recorded browser run <code>cc9680438496</code>.</strong> The fixed validation cohort contains 768 benign and 1,272 attack records. Always predicting the training majority (attack) scores <strong>62.353%</strong>. Round 0 is the untrained model, separate from that constant predictor and excluded from completed rounds.</p>

| Global model | Validation accuracy | Validation loss | Attack F1 | L2 weight change |
|---|---:|---:|---:|---:|
| Round 0 | 65.980% | 0.65066 | 78.567% | 0 |
| Round 1 | 99.902% | 0.08740 | 99.921% | 1.73797 |
| Round 2 | 99.902% | 0.00968 | 99.921% | 1.14914 |

<p align="justify">At Round 2, <strong>TN 767, FP 1, FN 1, TP 1,271</strong> give (767 + 1,271) / 2,040 = 99.902%. The two trained models made the same *number* of errors; their losses, parameter changes and checkpoint hashes distinguish them. An unchanged confusion matrix alone cannot tell whether the same individual rows were misclassified. The final model scored <strong>99.508%</strong> on the separate 2,034-record test cohort (9 missed attacks, 1 false alarm). This measures selected prefixes from three known devices. Capture-specific patterns, repeated observations within splits and correlated time windows limit generalization; this is not an estimate of deployment accuracy.</p>

<p align="justify">The main chart uses only full fixed-cohort evaluations. Offline trainers still have a separate, readable local validation partition on this host. A failed evaluator is recorded with coverage and a partial/unavailable label. Pooled precision, recall and F1 use summed confusion counts with attack positive; loss is averaged by evaluated records. Undefined ratios serialize as null and display as <strong>—</strong>. Training loss is stored separately. Validation can inform configuration decisions; avoid selecting configurations on final test scores.</p>

## Inspect and verify

- `sentinel/prepare.py` creates the cohort; `sentinel/federation.py` contains the model, clients and Flower strategy. `sentinel/service.py` owns scheduling and transactions; `sentinel/api.py` exposes the HTTP interface. `frontend/src/` contains the operator console.
- `state/sentinel.sqlite3` stores settings and run JSON snapshots. `state/checkpoints/<run-id>/round-NNN.npz` stores ordered global parameters. SHA-256 of each checkpoint equals its model version. The run also records the manifest fingerprint, per-device partition hashes, counts, configuration, attempts, validation results and final evaluation.
- `state/prepared/manifest.json` maps friendly IDs to original devices and file ranges. Keep the prepared directory unchanged while the service is running. For another experiment, prepare into a fresh directory with `--output PATH/prepared` and set `SENTINEL_HOME` to `PATH` before launch.
- [Verification record](docs/verification.md) links to the actual browser-run measurements. No fixture scores are used in the console or these figures.

<p align="justify">In a second PowerShell terminal, from the checkout root:</p>

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m scripts.smoke
```

<p align="justify">On Bash use the activated environment's <code>python</code> and <code>npm</code>. The smoke test operates the running local API, sets fleet power, runs two real training rounds and leaves the recorded result available. It refuses to take over an active run. Unit/integration tests use temporary directories and synthetic fixture records.</p>

## Privacy and future work

<p align="justify">Training inputs remain with their assigned logical client. Flower exchanges model parameters, example counts and local mean training losses. Local evaluators return aggregated confusion counts and losses. Preparation has access to all source files for the overlap audit. All components share one trusted host and process: this is logical separation, not an access-control boundary. Updates may reveal information. Differential privacy, secure aggregation, authenticated remote clients and encrypted transport are not implemented. Use the loopback binding for the demonstration.</p>

<p align="justify">Future work includes testing on unseen devices and later captures, Raspberry Pi gateways hosting local models for connected IoT devices, authenticated network transport, privacy-preserving aggregation and Docker packaging.</p>

## Project timeline

| Milestone | Deliverable |
|---|---|
| 1 · Dataset preparation | Three device partitions with ordered splits, local scalers and a duplicate audit. |
| 2 · Federated training | A PyTorch client per device and a Flower server that checks quorum on every round. |
| 3 · Operator console | Fleet power controls, run history and per-client evaluation backed by FastAPI and SQLite. |
| 4 · Demonstration | Browser and HTTP runs verified waiting, aggregation, disconnects, refresh and resumption. |

## Development roadmap

- [x] Reproduce the N-BaIoT demo from original captures on a fresh checkout.
- [x] Train with sample-weighted FedAvg and persist a checkpoint for each committed round.
- [x] Compare Round 0, the majority baseline and trained models on a fixed validation cohort.
- [x] Verify dashboard controls and publish the local setup guide and API reference.
- [ ] Evaluate on unseen devices and longer captures.
- [ ] Connect physical IoT devices through Raspberry Pi gateways.
- [ ] Add authenticated remote clients and encrypted transport.
- [ ] Evaluate differential privacy and secure aggregation.
- [ ] Package the service and dashboard for Docker.

## Author

<p align="justify"><strong>Spandan Palit</strong><br>
Btech - Computer Science &amp; Engineering<br>
Interested in AI/ML, Software Engineering, Internet of Things, Blockchain Technology and Cybersecurity</p>
