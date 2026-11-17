import hashlib
import json
import threading
import time
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from flwr.common import (
    ndarrays_to_parameters,
    parameters_to_ndarrays,
    FitRes,
    Status,
    Code,
)
from types import SimpleNamespace
from sentinel.api import create_app
from sentinel.federation import GatedAvg, Device, summarize
from sentinel.service import Coordinator
from scripts.smoke import exercise
from sentinel.prepare import FEATURES


@pytest.fixture
def home(tmp_path):
    p = tmp_path / "prepared"
    p.mkdir()
    clients = []
    for cid in ["1", "2", "3"]:
        rng = np.random.default_rng(int(cid))
        arrays = {}
        for k in ("train", "validation", "test"):
            arrays["X_" + k] = rng.normal(size=(12, 115)).astype("float32")
            arrays["y_" + k] = np.arange(12) % 2
        f = p / (cid + ".npz")
        np.savez(f, **arrays)
        clients.append(
            dict(
                id=cid,
                name="Client " + cid,
                device="fixture" + cid,
                partition_sha256=hashlib.sha256(f.read_bytes()).hexdigest(),
                counts={
                    k: dict(benign=6, attack=6) for k in ("train", "validation", "test")
                },
            )
        )
    (p / "manifest.json").write_text(
        json.dumps(dict(profile="fixture", clients=clients, features=FEATURES))
    )
    return tmp_path


def test_api_flow_and_checkpoint(home):
    with TestClient(create_app(home)) as c:
        r = exercise(c)
        for row in r["rounds"]:
            assert (
                hashlib.sha256((home / row["checkpoint"]).read_bytes()).hexdigest()
                == row["version"]
            )
    with TestClient(create_app(home)) as c:
        s = c.get("/api/state").json()
        assert (
            s["run"]["id"] == r["id"]
            and s["online"] == 3
            and s["run"]["completed"] == 2
        )


def test_weighted_reply_gate():
    def reply(i, n, v):
        return SimpleNamespace(cid=i), FitRes(
            Status(Code.OK, ""),
            ndarrays_to_parameters([np.array([v])]),
            n,
            {"training_loss": 1.0},
        )

    strategy = GatedAvg(inplace=False)
    strategy.permitted = lambda i: True
    strategy.minimum = 2
    replies = [reply("1", 100, 0.2), reply("2", 300, 0.8)]
    out, _ = strategy.aggregate_fit(1, replies, [])
    assert parameters_to_ndarrays(out)[0][0] == pytest.approx(0.65)
    strategy.permitted = lambda i: i == "1"
    assert strategy.aggregate_fit(1, replies, [])[0] is None


def test_disconnect_withdraws_update_and_retries(home, monkeypatch):
    entered = threading.Event()
    resume = threading.Event()
    original = Device.fit

    def pause(self, *args):
        if self.cid == "1":
            entered.set()
            assert resume.wait(15)
        return original(self, *args)

    monkeypatch.setattr(Device, "fit", pause)
    with TestClient(create_app(home)) as c:
        for i in range(1, 4):
            c.put(f"/api/devices/{i}/power", json={"online": True})
        rid = c.post("/api/runs", json={"rounds": 1}).json()["id"]
        assert entered.wait(20)
        c.put("/api/devices/1/power", json={"online": False})
        resume.set()

        def wait(status):
            end = time.monotonic() + 15
            while time.monotonic() < end:
                r = c.get("/api/runs/" + rid).json()
                if r["status"] == status:
                    return r
                time.sleep(0.05)
            pytest.fail(status)

        r = wait("waiting")
        assert (
            r["completed"] == 0
            and len(r["rounds"]) == 1
            and r["attempts"][0]["dropped"] == ["1"]
        )
        assert r["attempts"][0]["status"] == "insufficient replies"
        c.put("/api/devices/1/power", json={"online": True})
        r = wait("completed")
        assert [a["number"] for a in r["attempts"]] == [1, 1]
        assert r["attempts"][0]["input_version"] == r["attempts"][1]["input_version"]
        assert r["attempts"][1]["accepted"] == {"1": 12, "2": 12, "3": 12}


def test_stop_and_interruption(home):
    with TestClient(create_app(home)) as c:
        rid = c.post("/api/runs", json={}).json()["id"]
        assert c.post(f"/api/runs/{rid}/stop").status_code == 200
    s = Coordinator(home)
    assert s.run["status"] == "stopped"
    s.run["status"] = "training"
    s.run["attempts"].append({"id": 1, "status": "running"})
    s.save()
    s.close()
    s = Coordinator(home)
    assert (
        s.run["status"] == "interrupted"
        and s.run["attempts"][0]["status"] == "interrupted"
    )
    s.close()


def test_undefined_metrics():
    m = summarize([2, 0, 0, 0], 1.0)
    assert m["accuracy"] == 1 and m["precision"] is None and m["f1"] is None
