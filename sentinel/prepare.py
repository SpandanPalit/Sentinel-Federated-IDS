"""Prepare versioned, reproducible client partitions from Sentinel's N-BaIoT inputs."""

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from contextlib import ExitStack
from itertools import islice
from pathlib import Path

import numpy as np

DEVICES = (
    "Danmini_Doorbell",
    "Ecobee_Thermostat",
    "Ennio_Doorbell",
    "Philips_B120N10_Baby_Monitor",
    "Provision_PT_737E_Security_Camera",
    "Provision_PT_838_Security_Camera",
    "Samsung_SNH_1011_N_Webcam",
    "SimpleHome_XCS7_1002_WHT_Security_Camera",
    "SimpleHome_XCS7_1003_WHT_Security_Camera",
)
BASIC = ("weight", "mean", "variance")
PAIR = ("weight", "mean", "std", "magnitude", "radius", "covariance", "pcc")
FEATURES = [
    f"{group}_L{window}_{stat}"
    for group, stats in [
        ("MI_dir", BASIC),
        ("H", BASIC),
        ("HH", PAIR),
        ("HH_jit", BASIC),
        ("HpHp", PAIR),
    ]
    for window in ("5", "3", "1", "0.1", "0.01")
    for stat in stats
]
SPLITS = ("train", "validation", "test")
BENIGN_LIMIT = 1792
ATTACK_LIMIT = 256
GAP = 128


def capture_label(name):
    fields = name.split("/")
    if len(fields) == 2 and fields[-1] == "benign_traffic.csv":
        return 0
    if (
        len(fields) == 3
        and fields[1] in ("gafgyt_attacks", "mirai_attacks")
        and fields[-1].endswith(".csv")
    ):
        return 1
    return None


def read_capture(open_file, name, limit):
    with (
        open_file(name) as binary,
        io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as source,
    ):
        reader = csv.reader(source)
        header = next(reader, [])
        if header != FEATURES:
            pos = next(
                (i for i, (a, b) in enumerate(zip(header, FEATURES)) if a != b),
                min(len(header), 115),
            )
            raise ValueError(
                f"{name}: expected 115 ordered N-BaIoT features; first difference at column {pos + 1}"
            )
        rows = []
        for number, row in enumerate(islice(reader, limit), 2):
            try:
                values = np.asarray(row, dtype=np.float64)
                if len(values) != 115 or not np.isfinite(values).all():
                    raise ValueError()
            except ValueError as error:
                raise ValueError(
                    f"{name}, line {number}: expected 115 finite numeric values"
                ) from error
            rows.append(values)
    if not rows:
        raise ValueError(f"{name}: empty capture")
    return np.stack(rows)


def ranges(length, gap=GAP):
    # Smaller captures keep both gaps, each bounded to 1/8 of the available rows.
    if length < 5:
        raise ValueError("a split capture needs at least five ordered rows")
    gap = max(1, min(gap, length // 8))
    usable = length - gap * 2
    valid = max(1, usable // 6)
    train = usable - 2 * valid
    return [
        (0, train),
        (train + gap, train + gap + valid),
        (train + 2 * gap + valid, length),
    ]


def plan(names):
    """Keep capture files disjoint when possible; split only one capture if two exist."""
    plans = {name: {} for name in names}
    for label in (0, 1):
        group = sorted(name for name in names if capture_label(name) == label)
        if not group:
            raise ValueError(
                "Each device needs benign_traffic.csv and at least one extracted attack CSV"
            )
        if len(group) >= 3:
            holdout = max(1, round(len(group) * 0.2))
            for i, name in enumerate(group):
                split = (
                    "train"
                    if i < len(group) - 2 * holdout
                    else "validation"
                    if i < len(group) - holdout
                    else "test"
                )
                plans[name] = {split: "whole"}
        elif len(group) == 2:
            plans[group[0]] = {"train": "whole"}
            plans[group[1]] = {"validation": "first", "test": "last"}
        else:
            plans[group[0]] = dict(zip(SPLITS, range(3)))
    return plans


def transform(x, mean, scale):
    """Apply the same local, bounded standardization to all model inputs."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim not in (1, 2) or x.shape[-1] != 115 or not np.isfinite(x).all():
        raise ValueError("expected 115 finite features per observation")
    result = np.clip((x - mean) / scale, -12, 12).astype(np.float32)
    if not np.isfinite(result).all():
        raise ValueError("nonfinite normalized features")
    return result


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(raw=None, output=Path("state/prepared"), clients=3):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        base = Path(raw or "data/raw")
        if not base.is_dir():
            raise ValueError(
                f"No raw directory at {base}. See docs/data.md for manual placement."
            )
        names = [p.relative_to(base).as_posix() for p in base.glob("**/*.csv")]

        def opener(name):
            return (base / name).open("rb")
        devices = [d for d in DEVICES if any(n.startswith(d + "/") for n in names)][
            :clients
        ]
        if not devices:
            raise ValueError(
                "No recognized N-BaIoT device directories. See docs/data.md."
            )
        assignments, file_audit = {}, {}
        cache = output.parent / ".prepare-cache"
        cache.mkdir(exist_ok=True)
        for device in devices:
            selected = sorted(
                n
                for n in names
                if n.startswith(device + "/") and capture_label(n) is not None
            )
            assignments[device] = plan(selected)
            for name in selected:
                limit = ATTACK_LIMIT if capture_label(name) else BENIGN_LIMIT
                stat = (base / name).stat()
                tag = [
                    str(base.resolve()),
                    name,
                    stat.st_size,
                    stat.st_mtime_ns,
                    limit,
                ]
                key = hashlib.sha256(
                    json.dumps(["v1", FEATURES, tag]).encode()
                ).hexdigest()
                cached = cache / (key + ".npy")
                if not cached.exists():
                    values = read_capture(opener, name, limit)
                    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temp:
                        np.save(temp, values)
                    os.replace(temp.name, cached)
                file_audit[name] = cached
        generation = Path(
            stack.enter_context(tempfile.TemporaryDirectory(dir=output.parent))
        )
        manifest = {
            "dataset": "N-BaIoT",
            "profile": "demo",
            "features": FEATURES,
            "scaling": "local training mean/std; constant std=1; clip standardized inputs to [-12,12]",
            "source": "https://doi.org/10.24432/C5RC8J",
            "clients": [],
        }
        # Compare unscaled rows across ALL devices. Earlier splits take priority.
        previous = set()
        buffers = {d: {} for d in devices}
        reports = {
            d: {"sources": [], "counts": {}, "cross_split_removed": {}} for d in devices
        }
        for split in SPLITS:
            current = set()
            for device in devices:
                x_parts, y_parts, dropped = [], [], 0
                for name, spec in assignments[device].items():
                    if split not in spec:
                        continue
                    array = np.load(file_audit[name], mmap_mode="r")
                    index = spec[split]
                    start, end = (0, len(array))
                    if isinstance(index, int):
                        start, end = ranges(len(array))[index]
                    elif index in ("first", "last"):
                        spans = ranges(len(array))
                        start, end = spans[0 if index == "first" else 2]
                    values = np.array(array[start:end])
                    values[values == 0] = (
                        0  # normalize signed zeros for exact comparisons
                    )
                    keys = [hashlib.sha256(row.tobytes()).digest() for row in values]
                    mask = [k not in previous for k in keys]
                    current.update(k for k, keep in zip(keys, mask) if keep)
                    kept = values[mask]
                    x_parts.append(kept)
                    y_parts.append(
                        np.full(len(kept), capture_label(name), dtype=np.int64)
                    )
                    removed = len(values) - len(kept)
                    dropped += removed
                    reports[device]["sources"].append(
                        {
                            "file": name,
                            "split": split,
                            "rows_read": len(array),
                            "start": start,
                            "end_exclusive": end,
                            "selection": "capture prefix"
                            if index == "whole"
                            else "ordered block within prefix",
                            "raw_block_sha256": hashlib.sha256(
                                values.tobytes()
                            ).hexdigest(),
                            "overlap_removed": removed,
                        }
                    )
                x, y = np.concatenate(x_parts), np.concatenate(y_parts)
                counts = {"benign": int((y == 0).sum()), "attack": int((y == 1).sum())}
                if min(counts.values()) == 0:
                    raise ValueError(
                        f"{device} {split}: empty class after split/overlap audit: {counts}"
                    )
                buffers[device][split] = (x, y)
                reports[device]["counts"][split] = counts
                reports[device]["cross_split_removed"][split] = dropped
            previous.update(current)
        for i, device in enumerate(devices, 1):
            parts = buffers[device]
            mean = parts["train"][0].mean(axis=0)
            scale = parts["train"][0].std(axis=0)
            scale[scale == 0] = 1
            arrays = {"mean": mean, "scale": scale}
            for split, (x, y) in parts.items():
                arrays["X_" + split], arrays["y_" + split] = (
                    transform(x, mean, scale),
                    y,
                )
            file = generation / f"{i}.npz"
            np.savez_compressed(file, **arrays)
            client = {
                "id": str(i),
                "name": f"Client {i}",
                "device": device,
                "partition_sha256": digest(file),
                **reports[device],
            }
            manifest["clients"].append(client)
        serialized = json.dumps(manifest, indent=2) + "\n"
        (generation / "manifest.json").write_text(serialized, encoding="utf-8")
        if output.exists():
            existing = output / "manifest.json"
            if existing.is_file():
                saved = json.loads(existing.read_text(encoding="utf-8"))
                # Different zlib builds can serialize identical arrays to different ZIP bytes.
                if len(saved.get("clients", [])) == len(manifest["clients"]):
                    for old, new in zip(saved["clients"], manifest["clients"]):
                        path = output / f"{new['id']}.npz"
                        if not path.is_file() or digest(path) != old.get(
                            "partition_sha256"
                        ):
                            break
                        with (
                            np.load(path) as before,
                            np.load(generation / path.name) as after,
                        ):
                            if before.files != after.files or any(
                                not np.array_equal(before[k], after[k]) for k in after
                            ):
                                break
                        new["partition_sha256"] = old["partition_sha256"]
                    else:
                        if saved == manifest:
                            return saved
            raise ValueError(
                f"{output} contains different or incomplete data. Start in a fresh state directory."
            )
        # Publish all client files together after all checks have passed.
        os.replace(generation, output)
        return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw", type=Path, help="Directory containing extracted N-BaIoT device folders"
    )
    parser.add_argument("--output", type=Path, default=Path("state/prepared"))
    parser.add_argument("--clients", type=int, choices=range(1, 10), default=3)
    args = parser.parse_args()
    manifest = prepare(args.raw, args.output, args.clients)
    for client in manifest["clients"]:
        print(client["name"], client["device"], client["counts"])
