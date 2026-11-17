import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Counts = { benign: number; attack: number };
type Device = {
  id: string;
  name: string;
  device: string;
  online: boolean;
  eligible: boolean;
  activity: string;
  last: { run: string; number: number } | null;
  counts: Record<string, Counts>;
};
type Metric = Counts & {
  n: number;
  accuracy: number | null;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  loss: number | null;
  tn: number;
  fn: number;
  tp: number;
  fp: number;
};
type Evaluation = {
  pooled: Metric;
  clients: Record<string, Metric>;
  expected: number;
  evaluated: number;
  coverage: string;
};
type Round = {
  number: number;
  status: string;
  participants: string[];
  examples: number;
  ended: string;
  duration: number;
  version: string;
  delta: number;
  training_loss: number | null;
  validation: Evaluation;
};
type Run = {
  id: string;
  status: string;
  config: { rounds: number; review: boolean };
  attempts: {
    id: number;
    number: number;
    selected: string[];
    status: string;
  }[];
  completed: number;
  rounds: Round[];
  majority?: Metric & { prediction: number };
  test?: Evaluation;
  error?: string;
};
type State = {
  devices: Device[];
  minimum: number;
  profile: string;
  online: number;
  run: Run | null;
  ready: boolean;
};
const fmt = (v: number | null | undefined, pct = false) =>
  v == null ? "—" : pct ? (v * 100).toFixed(3) + "%" : v.toFixed(5);
const num = (n: number) => n.toLocaleString();
const active = (s?: string) =>
  !!s && !["completed", "stopped", "failed", "interrupted"].includes(s);
async function api(path: string, method = "GET", body?: unknown) {
  const res = await fetch("/api/" + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json();
    throw Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return res.json();
}
function Glyph({ kind }: { kind: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="21"
      height="21"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {kind === "shield" ? (
        <>
          <path d="M12 2 21 5v6c0 5-4 9-9 11-5-2-9-6-9-11V5z" />
          <path d="m7 12 3 0 2-5 2 9 2-4h2" />
        </>
      ) : kind === "device" ? (
        <>
          <rect x="6" y="6" width="12" height="12" rx="2" />
          <path d="M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3" />
          <rect x="10" y="10" width="4" height="4" />
        </>
      ) : (
        <>
          <path d="M12 2v9m-5-6a8 8 0 1 0 10 0" />
        </>
      )}
    </svg>
  );
}
function Chart({
  rows,
  k,
  title,
}: {
  rows: Round[];
  k: "accuracy" | "loss";
  title: string;
}) {
  const points = rows.filter(
      (r) => r.validation.coverage === "full" && r.validation.pooled[k] != null,
    ),
    vals = points.map((r) => r.validation.pooled[k]!),
    max = k === "accuracy" ? 1 : Math.max(0.01, ...vals) * 1.08;
  return (
    <article className="plot">
      <div className="plotTitle">
        {title}
        <small>{k === "accuracy" ? "0–100%" : "Cross-entropy"}</small>
      </div>
      {points.length ? (
        <>
          <svg
            viewBox="0 0 400 92"
            role="img"
            aria-label={title + " by completed round"}
          >
            {[10, 42, 76].map((y) => (
              <line
                key={y}
                x1="12"
                x2="384"
                y1={y}
                y2={y}
                stroke="#dde6e1"
                strokeDasharray="3 4"
              />
            ))}
            {points.map((r, i) => {
              const x =
                  12 + (370 * r.number) / Math.max(1, rows.at(-1)!.number),
                y = 76 - (64 * vals[i]) / max;
              return (
                <g key={r.number}>
                  {i > 0 && points[i - 1].number === r.number - 1 && (
                    <line
                      x1={
                        12 +
                        (370 * points[i - 1].number) /
                          Math.max(1, rows.at(-1)!.number)
                      }
                      y1={76 - (64 * vals[i - 1]) / max}
                      x2={x}
                      y2={y}
                      stroke={k === "loss" ? "#9a691b" : "#16836d"}
                      strokeWidth="2"
                    />
                  )}
                  <circle
                    cx={x}
                    cy={y}
                    r="3.5"
                    fill={
                      r.number === 0
                        ? "#697c75"
                        : k === "loss"
                          ? "#9a691b"
                          : "#16836d"
                    }
                  >
                    <title>
                      Round {r.number}: {fmt(vals[i], k === "accuracy")}
                    </title>
                  </circle>
                </g>
              );
            })}
          </svg>
          <small>
            R0 · untrained <span>R{rows.at(-1)?.number}</span>
          </small>
        </>
      ) : (
        <p className="empty">Awaiting full-cohort evaluation</p>
      )}
    </article>
  );
}
function App() {
  const [s, S] = useState<State | null>(null),
    [connected, C] = useState(false),
    [error, E] = useState(""),
    [busy, B] = useState(false),
    [target, T] = useState(3),
    [review, V] = useState(true),
    [pick, P] = useState(""),
    [historic, H] = useState<Run | null>(null),
    [history, L] = useState<{ id: string; status: string }[]>([]),
    [round, Q] = useState(-1);
  async function refresh() {
    try {
      const data = await api("state");
      S(data);
      C(true);
      L(await api("runs"));
    } catch {
      C(false);
    }
  }
  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 900);
    return () => clearInterval(t);
  }, []);
  async function cmd(path: string, method: string, body?: unknown) {
    B(true);
    try {
      await api(path, method, body);
      E("");
      await refresh();
    } catch (e) {
      E(String(e));
    } finally {
      B(false);
    }
  }
  const live = s?.run,
    run = pick && historic?.id === pick ? historic : live,
    rows = run?.rounds ?? [],
    row = round < 0 ? rows.at(-1) : rows.find((r) => r.number === round),
    ev = row?.validation,
    m = ev?.pooled,
    disabled = busy || !connected,
    on = s?.online ?? 0,
    min = s?.minimum ?? 0,
    total = s?.devices.length ?? 0;
  const waiting = live?.status === "waiting",
    last = live?.rounds.filter((r) => r.number > 0).at(-1),
    attempt = live?.attempts.at(-1);
  return (
    <>
      <header>
        <div className="identity">
          <i>
            <Glyph kind="shield" />
          </i>
          Sentinel <b> / </b>
          <small>Operations console</small>
        </div>
        <div className="headerState">
          <span className={"dot " + (connected ? "green" : "")} />
          {connected ? "Connected" : "Disconnected"}
          <em />
          {live?.status ?? "No active run"}
        </div>
      </header>
      <main>
        {error && (
          <aside role="alert">
            {error} <button onClick={() => E("")}>Dismiss</button>
          </aside>
        )}
        <section>
          <div className="sectionHead">
            <div className="kicker">01 / DEVICE OPERATIONS</div>
            <small className="mono">LOCAL INSTANCE</small>
          </div>
          <div className="heading">
            <h1>Device fleet</h1>
            <label className="pill">
              {on} online <b> / </b> {total} configured
            </label>
          </div>
          <div className="fleet">
            {s?.devices.map((d) => (
              <article
                className={"card device " + (d.online ? "online" : "")}
                key={d.id}
              >
                <div className="between">
                  <i className="chip">
                    <Glyph kind="device" />
                  </i>
                  <button
                    aria-label={"Power " + d.name}
                    role="switch"
                    aria-checked={d.online}
                    className={"toggle " + (d.online ? "on" : "")}
                    disabled={disabled}
                    onClick={() =>
                      cmd("devices/" + d.id + "/power", "PUT", {
                        online: !d.online,
                      })
                    }
                  >
                    <span />
                  </button>
                </div>
                <h3>{d.name}</h3>
                <div className="orig">{d.device.replaceAll("_", " ")}</div>
                <div className="deviceLine">
                  <span>
                    <i className={"dot " + (d.online ? "green" : "")} />
                    {d.online ? "Online" : "Offline"}
                  </span>
                  <span className="mono">{d.activity}</span>
                </div>
                <small>
                  {num(d.counts.train.benign + d.counts.train.attack)} training
                  records ·{" "}
                  {d.last ? "Last R" + d.last.number : "No participation"}
                </small>
              </article>
            ))}
          </div>
          {!total && (
            <div className="card empty">
              {connected
                ? "No devices prepared. Run python -m sentinel.prepare and restart the service."
                : "Awaiting backend connection"}
            </div>
          )}
        </section>
        <section>
          <div className="kicker">02 / ORCHESTRATION</div>
          <h2>Federation controls</h2>
          <div className="control card">
            <div className="form">
              <label>
                Minimum online
                <select
                  value={min}
                  disabled={disabled || !total}
                  onChange={(e) =>
                    cmd("threshold", "PUT", { minimum: +e.target.value })
                  }
                >
                  {s?.devices.map((_, i) => <option key={i}>{i + 1}</option>)}
                </select>
              </label>
              <label>
                Target rounds
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={active(live?.status) ? live?.config.rounds : target}
                  disabled={!!active(live?.status)}
                  onChange={(e) => T(+e.target.value)}
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={active(live?.status) ? live?.config.review : review}
                  disabled={!!active(live?.status)}
                  onChange={(e) => V(e.target.checked)}
                />
                Review between rounds
              </label>
              <div className="actions">
                <button
                  className="primary"
                  disabled={
                    disabled ||
                    !s?.ready ||
                    !!active(live?.status) ||
                    target < 1 ||
                    target > 100
                  }
                  onClick={() => {
                    P("");
                    Q(-1);
                    cmd("runs", "POST", { rounds: target, review });
                  }}
                >
                  ▷ Start run
                </button>
                <button
                  disabled={disabled || !active(live?.status)}
                  onClick={() => cmd("runs/" + live?.id + "/stop", "POST")}
                >
                  □ Stop
                </button>
              </div>
            </div>
            <div className={"notice " + (waiting ? "wait" : "")}>
              <strong>
                {waiting
                  ? "Waiting for " +
                    Math.max(0, min - on) +
                    " more client" +
                    (min - on === 1 ? "" : "s")
                  : live?.status === "review"
                    ? "Round complete · review boundary"
                    : on >= min && total
                      ? "Training quorum available"
                      : "Training quorum pending"}
              </strong>
              <span>
                {on} of {min} required online
              </span>
              {live?.status === "review" && (
                <button
                  onClick={() => cmd("runs/" + live.id + "/continue", "POST")}
                  disabled={disabled}
                >
                  Continue to next round →
                </button>
              )}
            </div>
          </div>
        </section>
        <section>
          <div className="kicker">03 / EXECUTION</div>
          <div className="heading">
            <h2>Training progress</h2>
            <span className="mono">
              {live ? "RUN / " + live.id : "NO ACTIVE RUN"}
            </span>
          </div>
          <div className="card progress">
            {[
              ["Run state", live?.status ?? "Idle"],
              [
                "Completed rounds",
                (live?.completed ?? 0) +
                  " / " +
                  (live?.config.rounds ?? target),
              ],
              [
                "Participants",
                (
                  (live?.status === "training"
                    ? attempt?.selected
                    : last?.participants) ?? []
                )
                  .map((i) => "C" + i)
                  .join(" · ") || "—",
              ],
              [
                "Last completion",
                last ? new Date(last.ended).toLocaleTimeString() : "—",
              ],
            ].map(([k, v]) => (
              <div key={k}>
                <small>{k}</small>
                <strong>{v}</strong>
              </div>
            ))}
          </div>
          {live?.status === "training" && (
            <p>
              Training round {attempt?.number} · attempt {attempt?.id}
            </p>
          )}
          {live?.error && <aside>{live.error}</aside>}
        </section>
        <section>
          <div className="kicker">04 / FIXED VALIDATION COHORT</div>
          <div className="heading">
            <h2>Model performance</h2>
            <div className="selectors">
              <select
                aria-label="Inspect run"
                value={pick}
                onChange={async (e) => {
                  const id = e.target.value;
                  P(id);
                  Q(-1);
                  if (id)
                    try {
                      H(await api("runs/" + id));
                    } catch (err) {
                      E(String(err));
                    }
                }}
              >
                <option value="">Latest run</option>
                {history
                  .filter((r) => r.id !== live?.id)
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.id} · {r.status}
                    </option>
                  ))}
              </select>
              <select
                aria-label="Inspect round"
                value={round}
                onChange={(e) => Q(+e.target.value)}
              >
                <option value={-1}>Latest model</option>
                {rows.map((r) => (
                  <option key={r.number} value={r.number}>
                    {r.number ? "Round " + r.number : "Round 0 · untrained"}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="card perf">
            <div className="between">
              <b>
                {row
                  ? row.number
                    ? "Round " + row.number
                    : "Round 0 · untrained"
                  : "Awaiting evaluation"}
              </b>
              <span className="mono">
                {ev
                  ? ev.coverage +
                    " · " +
                    ev.evaluated +
                    "/" +
                    ev.expected +
                    " evaluators"
                  : "VALIDATION"}
              </span>
            </div>
            <div className="metrics">
              {(["accuracy", "loss", "precision", "recall", "f1"] as const).map(
                (k) => (
                  <div key={k}>
                    <small>
                      {k === "loss"
                        ? "Validation loss"
                        : k === "accuracy"
                          ? "Accuracy"
                          : "Attack " + k.toUpperCase()}
                    </small>
                    <strong>{fmt(m?.[k], k !== "loss")}</strong>
                  </div>
                ),
              )}
            </div>
            <div className="meta">
              Profile: {s?.profile ?? "—"} · {num(m?.benign ?? 0)} benign /{" "}
              {num(m?.attack ?? 0)} attack evaluated · Majority baseline:{" "}
              {fmt(run?.majority?.accuracy, true)}{" "}
              {run?.majority
                ? "(" + (run.majority.prediction ? "attack" : "benign") + ")"
                : ""}
            </div>
          </div>
          <div className="charts">
            <Chart rows={rows} k="accuracy" title="Validation accuracy" />
            <Chart rows={rows} k="loss" title="Validation loss" />
          </div>
          <details open={undefined}>
            <summary>Confusion matrix & per-client results</summary>
            {m && row ? (
              <>
                <p>
                  Run {run?.id} · model {row.version.slice(0, 14)} · parameter
                  change L2 {fmt(row.delta)} · training loss{" "}
                  {fmt(row.training_loss)}
                </p>
                <table>
                  <caption>
                    Actual class (rows) / predicted class (columns)
                  </caption>
                  <thead>
                    <tr>
                      <th>Actual</th>
                      <th>Benign</th>
                      <th>Attack</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Benign</td>
                      <td>TN {num(m.tn)}</td>
                      <td>FP {num(m.fp)}</td>
                    </tr>
                    <tr>
                      <td>Attack</td>
                      <td>FN {num(m.fn)}</td>
                      <td>TP {num(m.tp)}</td>
                    </tr>
                  </tbody>
                </table>
                <div className="scroll">
                  <table>
                    <thead>
                      <tr>
                        {[
                          "Client",
                          "Benign",
                          "Attack",
                          "Accuracy",
                          "Loss",
                          "Precision",
                          "Recall",
                          "F1",
                        ].map((t) => (
                          <th key={t}>{t}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(ev!.clients).map(([id, v]) => (
                        <tr key={id}>
                          <td>Client {id}</td>
                          <td>{v.benign}</td>
                          <td>{v.attack}</td>
                          <td>{fmt(v.accuracy, true)}</td>
                          <td>{fmt(v.loss)}</td>
                          <td>{fmt(v.precision, true)}</td>
                          <td>{fmt(v.recall, true)}</td>
                          <td>{fmt(v.f1, true)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p>Awaiting evaluation</p>
            )}
          </details>
        </section>
        <section>
          <div className="kicker">05 / AUDIT LOG</div>
          <h2>Round history</h2>
          <div className="scroll card">
            <table>
              <thead>
                <tr>
                  {[
                    "Round",
                    "Status",
                    "Clients",
                    "Train samples",
                    "Duration",
                    "Accuracy",
                    "Δ weights",
                  ].map((x) => (
                    <th key={x}>{x}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...rows].reverse().map((r) => (
                  <tr key={r.number}>
                    <td>
                      <button className="link" onClick={() => Q(r.number)}>
                        R{r.number}
                      </button>
                    </td>
                    <td>{r.status}</td>
                    <td>
                      {r.participants.map((i) => "C" + i).join(", ") || "—"}
                    </td>
                    <td>{num(r.examples)}</td>
                    <td>{r.duration.toFixed(2)} s</td>
                    <td>{fmt(r.validation.pooled.accuracy, true)}</td>
                    <td>{fmt(r.delta)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <p className="empty">No committed models yet</p>}
          </div>
          {run && (
            <details>
              <summary>Training attempts ({run.attempts.length})</summary>
              {run.attempts.map((a) => (
                <p key={a.id}>
                  Attempt {a.id} · Round {a.number} · Clients{" "}
                  {a.selected.join(", ")} · {a.status}
                </p>
              ))}
            </details>
          )}
        </section>
        <footer>
          Sentinel / Local federation console{" "}
          <a href="/docs">API documentation ↗</a>
        </footer>
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
