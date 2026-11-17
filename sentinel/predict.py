"""Label an ordered N-BaIoT CSV prefix using a saved Sentinel round and client scaler."""

import argparse
import json
import sqlite3
from functools import partial
from pathlib import Path

import numpy as np
import torch

from .federation import load_weights, model
from .prepare import digest, read_capture, transform


def predict(home, run_id, number, client_id, csv_file, limit):
    if limit < 1:
        raise ValueError("--limit must be positive")
    with sqlite3.connect(
        (home / "sentinel.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        result = db.execute("SELECT body FROM runs WHERE id=?", (run_id,)).fetchone()
    if not result:
        raise ValueError("Unknown run ID")
    run = json.loads(result[0])
    client = next((c for c in run["cohort"] if c["id"] == client_id), None)
    row = next((r for r in run["rounds"] if r["number"] == number), None)
    if client is None or row is None:
        raise ValueError("Client or committed model round is missing from this run")
    partition = home / "prepared" / f"{client_id}.npz"
    ckpt = home / row["checkpoint"]
    if (
        digest(partition) != client["partition_sha256"]
        or digest(ckpt) != row["version"]
    ):
        raise ValueError(
            "The selected partition or checkpoint differs from the recorded run"
        )
    samples = read_capture(partial(open, mode="rb"), str(csv_file), limit)
    with np.load(partition) as part:
        x = transform(samples, part["mean"], part["scale"])
    network = model()
    with np.load(ckpt) as saved:
        load_weights(network, [saved[f"arr_{i}"] for i in range(len(saved.files))])
    network.eval()
    with torch.inference_mode():
        labels = network(torch.from_numpy(x)).argmax(dim=1).tolist()
    return {
        "run": run_id,
        "round": number,
        "version": row["version"],
        "client": client_id,
        "labels": labels,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("state"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    print(
        json.dumps(
            predict(
                args.state, args.run, args.round, args.client, args.csv, args.limit
            ),
            indent=2,
        )
    )
