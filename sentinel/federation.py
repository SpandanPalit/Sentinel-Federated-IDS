"""Local Flower transport: real FitIns/FitRes messages, Server.fit_round and FedAvg."""

import hashlib
from pathlib import Path

import numpy as np
import torch
from torch import nn
from flwr.client import NumPyClient
from flwr.common import (
    DisconnectRes,
    FitIns,
    EvaluateIns,
    ndarrays_to_parameters,
    parameters_to_ndarrays,
)
from flwr.server import Server
from flwr.server.client_manager import SimpleClientManager
from flwr.server.client_proxy import ClientProxy
from flwr.server.strategy import FedAvg


def model():
    return nn.Sequential(
        nn.Linear(115, 64), nn.ReLU(), nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 2)
    )


def weights(net):
    return [p.detach().cpu().numpy().copy() for p in net.parameters()]


def load_weights(net, arrays):
    with torch.no_grad():
        for p, a in zip(net.parameters(), arrays, strict=True):
            p.copy_(torch.from_numpy(a))


def summarize(counts, loss_sum):
    tn, fp, fn, tp = (int(k) for k in counts)
    n = tn + fp + fn + tp
    ratio = lambda a, b: a / b if b else None
    return dict(
        tn=tn,
        fp=fp,
        fn=fn,
        tp=tp,
        n=n,
        benign=tn + fp,
        attack=fn + tp,
        accuracy=ratio(tn + tp, n),
        precision=ratio(tp, tp + fp),
        recall=ratio(tp, tp + fn),
        f1=ratio(2 * tp, 2 * tp + fp + fn),
        loss=ratio(loss_sum, n) if loss_sum is not None else None,
    )


class Device(NumPyClient):
    def __init__(self, path, cid, permitted):
        self.cid, self.permitted = cid, permitted
        with np.load(path) as src:
            self.parts = {
                k: (
                    torch.from_numpy(src["X_" + k].astype("float32")),
                    torch.from_numpy(src["y_" + k].astype("int64")),
                )
                for k in ("train", "validation", "test")
            }

    def fit(self, parameters, config):
        net = model()
        load_weights(net, parameters)
        x, y = self.parts["train"]
        opt = torch.optim.Adam(net.parameters(), lr=config["lr"])
        gen = torch.Generator().manual_seed(
            config["seed"] + 1009 * config["round"] + int(self.cid)
        )
        total = 0.0
        for _ in range(config["epochs"]):
            for idx in torch.randperm(len(y), generator=gen).split(config["batch"]):
                if not self.permitted(self.cid):
                    raise RuntimeError(
                        f"Client {self.cid}: training eligibility withdrawn"
                    )
                opt.zero_grad()
                loss = nn.functional.cross_entropy(net(x[idx]), y[idx])
                loss.backward()
                opt.step()
                total += loss.item() * len(idx)
        return (
            weights(net),
            len(y),
            {"training_loss": total / (len(y) * config["epochs"])},
        )

    def evaluate(self, parameters, config):
        net = model()
        load_weights(net, parameters)
        net.eval()
        x, y = self.parts[config["split"]]
        counts, total = torch.zeros(4, dtype=torch.long), 0.0
        with torch.inference_mode():
            for xb, yb in zip(x.split(1024), y.split(1024)):
                logits = net(xb)
                total += nn.functional.cross_entropy(logits, yb, reduction="sum").item()
                counts += torch.bincount(2 * yb + logits.argmax(1), minlength=4)
        return (
            total / len(y),
            len(y),
            dict(zip(("tn", "fp", "fn", "tp"), counts.tolist())),
        )


class LocalProxy(ClientProxy):
    """In-process message adapter; Flower serializes parameter arrays on exchange."""

    def __init__(self, cid, device):
        super().__init__(cid)
        self.client = device.to_client()

    def fit(self, ins, timeout, group_id):
        return self.client.fit(ins)

    def evaluate(self, ins, timeout, group_id):
        return self.client.evaluate(ins)

    def get_parameters(self, ins, timeout, group_id):
        return self.client.get_parameters(ins)

    def get_properties(self, ins, timeout, group_id):
        return self.client.get_properties(ins)

    def reconnect(self, ins, timeout, group_id):
        return DisconnectRes(reason="local")


class GatedAvg(FedAvg):
    def configure_fit(self, server_round, parameters, client_manager):
        return [
            (client_manager.all()[cid], FitIns(parameters, self.config))
            for cid in self.selected
        ]

    def aggregate_fit(self, server_round, results, failures):
        # Final eligibility snapshot is the reply acceptance boundary.
        accepted = [(c, r) for c, r in results if self.permitted(c.cid)]
        self.accepted = {c.cid: r.num_examples for c, r in accepted}
        self.train_loss = (
            sum(r.metrics["training_loss"] * r.num_examples for c, r in accepted)
            / sum(self.accepted.values())
            if accepted
            else None
        )
        if len(accepted) < self.minimum:
            return None, {}
        return super().aggregate_fit(server_round, accepted, failures)


class Federation:
    def __init__(self, root: Path, clients, config, permitted):
        torch.set_num_threads(1)
        torch.manual_seed(config["seed"])
        self.manager = SimpleClientManager()
        for c in clients:
            cid = c["id"]
            self.manager.register(
                LocalProxy(cid, Device(root / (cid + ".npz"), cid, permitted))
            )
        initial = ndarrays_to_parameters(weights(model()))
        self.strategy = GatedAvg(initial_parameters=initial, inplace=False)
        self.strategy.permitted = permitted
        self.server = Server(client_manager=self.manager, strategy=self.strategy)
        self.server.max_workers = 1  # modest CPU use, deterministic scheduling
        self.server.parameters = self.strategy.initialize_parameters(self.manager)

    def fit(self, number, selected, minimum, config):
        s = self.strategy
        s.selected, s.minimum, s.config = selected, minimum, {**config, "round": number}
        new, _, (_, failures) = self.server.fit_round(number, None)
        return new, s.accepted, s.train_loss, [str(f) for f in failures]

    def evaluate(self, params, split):
        rows, errors = {}, {}
        for cid, proxy in self.manager.all().items():
            try:
                reply = proxy.evaluate(
                    EvaluateIns(params, {"split": split}), None, None
                )
                rows[cid] = summarize(
                    [reply.metrics[k] for k in ("tn", "fp", "fn", "tp")],
                    reply.loss * reply.num_examples,
                )
            except Exception as exc:
                errors[cid] = str(exc)
        pooled = summarize(
            [sum(r[k] for r in rows.values()) for k in ("tn", "fp", "fn", "tp")],
            sum(r["loss"] * r["n"] for r in rows.values()),
        )
        return dict(
            pooled=pooled,
            clients=rows,
            errors=errors,
            coverage="full" if not errors else ("partial" if rows else "unavailable"),
            expected=len(self.manager.all()),
            evaluated=len(rows),
        )


def checkpoint(directory, number, params, previous):
    arrays = parameters_to_ndarrays(params)
    delta = float(
        np.sqrt(
            sum(
                np.square(a.astype("float64") - b).sum()
                for a, b in zip(arrays, parameters_to_ndarrays(previous))
            )
        )
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"round-{number:03}.npz"
    np.savez(path, *arrays)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return str(path), digest, delta
