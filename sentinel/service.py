"""One process owns the coordinator. SQLite transactions publish complete run snapshots."""

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException

from .federation import Federation, checkpoint, summarize


def now():
    return datetime.now(timezone.utc).isoformat()


ACTIVE = {
    "initializing",
    "waiting",
    "training",
    "evaluating",
    "between rounds",
    "review",
    "stopping",
}


class Coordinator:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.cv = threading.Condition(threading.RLock())
        self.db = sqlite3.connect(
            self.home / "sentinel.sqlite3", check_same_thread=False
        )
        self.db.execute("pragma journal_mode=WAL")
        self.db.executescript(
            "create table if not exists runs(id text primary key, body text not null); create table if not exists settings(key text primary key, body text not null);"
        )
        self.run = self.worker = None
        self.stop = self.release = False
        self.lease = {}
        src = self.home / "prepared" / "manifest.json"
        self.manifest = (
            json.loads(src.read_text(encoding="utf-8"))
            if src.exists()
            else {"clients": [], "profile": None}
        )
        self.fingerprint = (
            hashlib.sha256(src.read_bytes()).hexdigest() if src.exists() else None
        )
        self.clients = self.manifest["clients"]
        self.data_error = None
        for client in self.clients:
            part = self.home / "prepared" / (client["id"] + ".npz")
            if (
                not part.is_file()
                or hashlib.sha256(part.read_bytes()).hexdigest()
                != client["partition_sha256"]
            ):
                self.data_error = f"Prepared partition for Client {client['id']} is missing or changed"
                break
        self.data_ready = bool(self.clients) and self.data_error is None
        self.devices = {
            c["id"]: self.setting(
                "device:" + c["id"], {"online": False, "generation": 0, "last": None}
            )
            for c in self.clients
        }
        self.minimum = min(len(self.clients), max(1, self.setting("minimum", 3)))
        latest = self.db.execute(
            "select body from runs order by rowid desc limit 1"
        ).fetchone()
        if latest:
            self.run = json.loads(latest[0])
            if self.run["status"] in ACTIVE:
                self.run["status"] = "interrupted"
                self.run["ended"] = now()
                for a in self.run["attempts"]:
                    if a["status"] == "running":
                        a.update(status="interrupted", ended=now())
                self.save()

    def setting(self, key, default):
        row = self.db.execute(
            "select body from settings where key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute(
            "insert or replace into settings values(?,?)", (key, json.dumps(value))
        )

    def save(self):
        self.db.execute(
            "insert into runs values(?,?) on conflict(id) do update set body=excluded.body",
            (self.run["id"], json.dumps(self.run, allow_nan=False)),
        )
        self.db.commit()

    def status(self, value):
        if self.run["status"] != value:
            self.run["status"] = value
            self.save()

    def online(self):
        return [cid for cid, d in self.devices.items() if d["online"]]

    def permitted(self, cid):
        with self.cv:
            d = self.devices[cid]
            return (
                not self.stop and d["online"] and self.lease.get(cid) == d["generation"]
            )

    def power(self, cid, value):
        with self.cv:
            if cid not in self.devices:
                raise HTTPException(404, "Unknown client")
            d = self.devices[cid]
            if d["online"] != value:
                d["online"] = value
                d["generation"] += 1
                self.put("device:" + cid, d)
                self.db.commit()
                self.cv.notify_all()
            return dict(id=cid, online=value)

    def threshold(self, value):
        with self.cv:
            if not 1 <= value <= len(self.clients):
                raise HTTPException(
                    422, "Minimum must be between 1 and the configured device count"
                )
            self.minimum = value
            self.put("minimum", value)
            self.db.commit()
            self.cv.notify_all()
            return {"minimum": value}

    def state(self):
        with self.cv:
            active = self.run and self.run["status"] == "training"
            devices = [
                {
                    **c,
                    **self.devices[c["id"]],
                    "eligible": self.devices[c["id"]]["online"],
                    "activity": "training"
                    if active and self.permitted(c["id"])
                    else "idle",
                }
                for c in self.clients
            ]
            return dict(
                devices=devices,
                profile=self.manifest["profile"],
                minimum=self.minimum,
                online=len(self.online()),
                run=json.loads(json.dumps(self.run)),
                ready=self.data_ready,
            )

    def history(self):
        with self.cv:
            return [
                {k: r[k] for k in ("id", "started", "status", "completed")}
                for (body,) in self.db.execute(
                    "select body from runs order by rowid desc"
                )
                for r in [json.loads(body)]
            ]

    def get(self, rid):
        with self.cv:
            row = self.db.execute("select body from runs where id=?", (rid,)).fetchone()
            if not row:
                raise HTTPException(404, "Unknown run")
            return json.loads(row[0])

    def start(self, config):
        with self.cv:
            if self.worker and self.worker.is_alive():
                raise HTTPException(409, "Run already active")
            if not self.data_ready:
                raise HTTPException(
                    409, self.data_error or "Prepare N-BaIoT and restart Sentinel first"
                )
            rid = uuid.uuid4().hex[:12]
            self.stop = self.release = False
            self.run = dict(
                id=rid,
                started=now(),
                ended=None,
                status="initializing",
                config=config,
                cohort=self.clients,
                profile=self.manifest["profile"],
                manifest_sha256=self.fingerprint,
                initial_minimum=self.minimum,
                completed=0,
                rounds=[],
                attempts=[],
                test=None,
                error=None,
            )
            self.save()
            self.worker = threading.Thread(
                target=self.loop, name="sentinel-coordinator", daemon=True
            )
            self.worker.start()
            return {"id": rid}

    def command(self, rid, action):
        with self.cv:
            if (
                not self.run
                or self.run["id"] != rid
                or self.run["status"] not in ACTIVE
            ):
                raise HTTPException(409, "No matching active run")
            if action == "stop":
                self.stop = True
                self.status("stopping")
            elif self.run["status"] == "review":
                self.release = True
            else:
                raise HTTPException(409, "Run is not at a review boundary")
            self.cv.notify_all()
            return {"id": rid, "command": action}

    def loop(self):
        r = self.run
        cfg = r["config"]
        try:
            fed = Federation(self.home / "prepared", self.clients, cfg, self.permitted)
            cnt = lambda split, key: sum(c["counts"][split][key] for c in self.clients)
            major = int(cnt("train", "attack") > cnt("train", "benign"))
            b, a = cnt("validation", "benign"), cnt("validation", "attack")
            with self.cv:
                r["majority"] = {
                    "prediction": major,
                    **summarize([0, b, 0, a] if major else [b, 0, a, 0], None),
                }
            for n in range(cfg["rounds"] + 1):
                while True:
                    with self.cv:
                        if self.stop:
                            return
                        if n and len(self.online()) < self.minimum:
                            self.status("waiting")
                            self.cv.wait()
                            continue
                        if n:
                            ids = self.online()
                            minimum = self.minimum
                            self.lease = {
                                cid: self.devices[cid]["generation"] for cid in ids
                            }
                            attempt = dict(
                                id=len(r["attempts"]) + 1,
                                number=n,
                                selected=ids,
                                minimum=minimum,
                                started=now(),
                                status="running",
                                input_version=r["rounds"][-1]["version"],
                            )
                            r["attempts"].append(attempt)
                            r["status"] = "training"
                            self.save()
                    start = time.monotonic()
                    prev = fed.server.parameters
                    if n:
                        new, accepted, train_loss, errors = fed.fit(
                            n, ids, minimum, cfg
                        )
                        with self.cv:
                            attempt.update(
                                accepted=accepted,
                                errors=errors,
                                ended=now(),
                                dropped=[i for i in ids if i not in accepted],
                            )
                            if new is None or self.stop:
                                attempt["status"] = (
                                    "stopped" if self.stop else "insufficient replies"
                                )
                                self.save()
                                if self.stop:
                                    return
                                self.status("between rounds")
                                self.cv.wait(timeout=1)
                                continue
                    else:
                        new, accepted, train_loss = prev, {}, None
                    with self.cv:
                        self.status("evaluating")
                    metrics = fed.evaluate(new, "validation")
                    with self.cv:
                        if self.stop:
                            if n:
                                attempt["status"] = "stopped"
                            return
                        path, version, delta = checkpoint(
                            self.home / "checkpoints" / r["id"], n, new, prev
                        )
                        row = dict(
                            number=n,
                            status="committed" if n else "baseline",
                            ended=now(),
                            duration=time.monotonic() - start,
                            version=version,
                            checkpoint=Path(path).relative_to(self.home).as_posix(),
                            delta=delta,
                            participants=list(accepted),
                            examples=sum(accepted.values()),
                            training_loss=train_loss,
                            validation=metrics,
                        )
                        if n:
                            attempt.update(status="committed", version=version)
                            for cid in accepted:
                                self.devices[cid]["last"] = dict(run=r["id"], number=n)
                                self.put("device:" + cid, self.devices[cid])
                        r["rounds"].append(row)
                        r["completed"] = n
                        fed.server.parameters = new
                        self.save()
                    break
                if 0 < n < cfg["rounds"] and cfg["review"]:
                    with self.cv:
                        self.release = False
                        self.status("review")
                        self.cv.wait_for(lambda: self.stop or self.release)
                        if self.stop:
                            return
            with self.cv:
                self.status("evaluating")
            final = fed.evaluate(fed.server.parameters, "test")
            with self.cv:
                if not self.stop:
                    r["test"] = {"version": r["rounds"][-1]["version"], **final}
                    self.status("completed")
        except Exception as e:
            with self.cv:
                r.update(status="failed", error=f"{type(e).__name__}: {e}")
                for att in r["attempts"]:
                    if att["status"] == "running":
                        att.update(status="failed", ended=now())
        finally:
            with self.cv:
                if self.stop:
                    r["status"] = "stopped"
                r["ended"] = now()
                self.lease = {}
                self.save()

    def close(self):
        with self.cv:
            self.stop = True
            self.cv.notify_all()
        if self.worker:
            self.worker.join()
        self.db.close()
