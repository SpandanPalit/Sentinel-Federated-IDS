"""Response contracts shared by Swagger and the operations console."""

from typing import Any, Literal
from pydantic import BaseModel


class Counts(BaseModel):
    benign: int
    attack: int


class Client(BaseModel):
    id: str
    name: str
    device: str
    partition_sha256: str
    counts: dict[str, Counts]


class DeviceView(Client):
    online: bool
    generation: int
    last: dict | None
    eligible: bool
    activity: str


class Metrics(Counts):
    n: int
    tn: int
    fp: int
    fn: int
    tp: int
    accuracy: float | None
    precision: float | None
    recall: float | None
    f1: float | None
    loss: float | None


class Evaluation(BaseModel):
    pooled: Metrics
    clients: dict[str, Metrics]
    errors: dict[str, str]
    expected: int
    evaluated: int
    coverage: Literal["full", "partial", "unavailable"]


class FinalEvaluation(Evaluation):
    version: str


class Round(BaseModel):
    number: int
    status: str
    ended: str
    duration: float
    version: str
    checkpoint: str
    delta: float
    participants: list[str]
    examples: int
    training_loss: float | None
    validation: Evaluation


class RunInfo(BaseModel):
    id: str
    started: str
    status: str
    completed: int


class Run(RunInfo):
    ended: str | None
    config: dict[str, Any]
    cohort: list[dict]
    profile: str
    manifest_sha256: str
    initial_minimum: int
    majority: dict | None = None
    rounds: list[Round]
    attempts: list[dict]
    test: FinalEvaluation | None
    error: str | None


class Snapshot(BaseModel):
    devices: list[DeviceView]
    profile: str | None
    minimum: int
    online: int
    ready: bool
    run: Run | None
