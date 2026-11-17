"""Exercise the local demo over HTTP. Changes power states and creates a 2-round run."""

import argparse
import time

import httpx


def exercise(client):
    def call(method, path, **kwargs):
        response = client.request(method, "/api/" + path, **kwargs)
        response.raise_for_status()
        return response.json()

    def wait(status):
        end = time.monotonic() + 90
        while time.monotonic() < end:
            r = call("GET", "runs/" + rid)
            if r["status"] == status:
                return r
            if r["status"] in ("failed", "stopped", "interrupted"):
                raise AssertionError(r["error"] or r["status"])
            time.sleep(0.08)
        raise TimeoutError(status)

    devices = call("GET", "devices")
    assert len(devices) >= 3, "Prepare at least three real devices first"
    if any(
        r["status"] not in ("completed", "failed", "stopped", "interrupted")
        for r in call("GET", "runs")
    ):
        raise RuntimeError("Stop the existing run before smoke testing")
    ids = [d["id"] for d in devices[:3]]

    def power(cid, online):
        return call("PUT", f"devices/{cid}/power", json={"online": online})

    for d in devices:
        power(d["id"], d["id"] in ids[:2])
    power(ids[0], True)
    call("PUT", "threshold", json={"minimum": 3})
    assert (
        client.put("/api/threshold", json={"minimum": len(devices) + 1}).status_code
        == 422
    )
    rid = call("POST", "runs", json={"rounds": 2, "review": True})["id"]
    assert client.post("/api/runs", json={}).status_code == 409
    r = wait("waiting")
    assert (
        r["completed"] == 0
        and len(r["rounds"]) == 1
        and call("GET", "state")["online"] == 2
    )
    power(ids[2], True)
    r = wait("review")
    first = r["rounds"][1]
    assert first["delta"] > 0 and set(first["participants"]) == set(ids)
    power(ids[2], False)
    call("POST", "runs/" + rid + "/continue")
    r = wait("waiting")
    assert r["completed"] == 1 and r["rounds"][1] == first
    power(ids[2], True)
    r = wait("completed")
    assert (
        r["completed"] == 2
        and len(r["rounds"]) == 3
        and r["test"]["version"] == r["rounds"][2]["version"]
    )
    for row in r["rounds"]:
        assert call("GET", f"runs/{rid}/rounds/{row['number']}") == row
        m = row["validation"]["pooled"]
        assert (
            row["validation"]["coverage"] == "full"
            and m["accuracy"] == (m["tp"] + m["tn"]) / m["n"]
        )
    return r


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    with httpx.Client(
        base_url=p.parse_args().url, timeout=15, trust_env=False
    ) as client:
        run = exercise(client)
        print(
            "PASS",
            run["id"],
            run["completed"],
            "trained rounds;",
            run["rounds"][-1]["validation"]["pooled"],
        )
