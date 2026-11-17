# Sentinel verification record

The original checkout contained no application, dependencies, dataset or startup files. A local copy of the original N-BaIoT captures was available on the demonstration machine. Fresh clones reproduce the demo from the original device directories.

| Check | Entry point | Observed outcome |
|---|---|---|
| Data preparation | `python -m sentinel.prepare --raw <extracted directory>` | Three partitions reproduced from local originals. 6,912 training, 2,040 validation, 2,034 test records retained. |
| Automated tests | `python -m pytest -q` | 7 passed. Fixture data only: schema, nonfinite input, train-only scaler, duplicate rows, checkpoint identity, refresh/restart, controls, interrupted state, weighted averaging, disconnect/retry and undefined ratios. Four upstream deprecation warnings. |
| Frontend | `npm --prefix frontend run build` | TypeScript check and Vite production build passed. Served HTML and assets from FastAPI. |
| Browser | Fleet switches, start, review, continue, page refresh | Run **cc9680438496**. Two online waited with baseline only. Third switch committed R1 with 3 clients. Power-off at review followed by Continue held R2; refresh preserved 2/3, same run ID and measured R1. Power-on committed R2. |
| HTTP smoke | `python -m scripts.smoke` against restarted final build | Run **ae8717de0f79**, two real rounds committed. Flower logged 3 results and 0 failures on both rounds. Tests cross-checked returned confusion counts against accuracy and the per-round route. |
| Offline inference | `python -m sentinel.predict` on a separate isolated real run | Verified saved scaler and checkpoint before predicting three original CSV rows. This run completed one real Flower round in temporary state. |
| Documentation | Compare GET /openapi.json with docs/openapi.json; GET /docs and its local JS and CSS | Schema matched; all returned 200. |

**Five real training rounds** across verification: two from the browser, two from the repeatable HTTP smoke run, and one isolated inference check. Round 0 is excluded. The two primary runs and their checkpoints remain in the local state directory. The [browser run JSON](evidence/browser-run.json) and [HTTP smoke run JSON](evidence/http-run.json) are exported evidence, never injected into the console. The [dashboard capture](dashboard.jpg) shows the final HTTP run.

The measured plateau is real for this profile: Round 1 and Round 2 each made two validation errors. The second aggregation nevertheless moved the parameters (L2 ≈ 1.14914), and validation cross-entropy fell from about 0.08740 to 0.00968. No claim about unseen devices or long-term traffic follows from this cohort. All client trainers and evaluators share a host; disconnect tests withdraw logical training eligibility rather than unplugging hardware.
