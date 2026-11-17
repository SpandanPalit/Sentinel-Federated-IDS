from contextlib import asynccontextmanager
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from .service import Coordinator
from . import views
from fastapi.openapi.docs import get_swagger_ui_html


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Power(Body):
    online: bool


class Threshold(Body):
    minimum: int


class RunConfig(Body):
    rounds: int = Field(3, ge=1, le=100)
    epochs: int = Field(1, ge=1, le=20)
    batch: int = Field(64, ge=1, le=4096)
    lr: float = Field(0.001, gt=0, le=1)
    seed: int = Field(42, ge=0, le=2147483647)
    review: bool = False


def create_app(home=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.s = Coordinator(home or os.environ.get("SENTINEL_HOME", "state"))
        try:
            yield
        finally:
            app.state.s.close()

    app = FastAPI(
        title="Sentinel",
        docs_url=None,
        redoc_url=None,
        version="1.0.0",
        description="Local IoT federation control and measured model evaluations.",
        lifespan=lifespan,
    )

    def s():
        return app.state.s

    @app.get("/api/health")
    def health():
        return {
            "backend": "online",
            "runtime_ready": True,
            "data_ready": s().data_ready,
            "data_error": s().data_error,
            "profile": s().manifest["profile"],
        }

    @app.get("/api/state", response_model=views.Snapshot)
    def state():
        return s().state()

    @app.get("/api/devices", response_model=list[views.DeviceView])
    def devices():
        return s().state()["devices"]

    @app.put("/api/devices/{cid}/power")
    def power(cid: str, body: Power):
        return s().power(cid, body.online)

    @app.get("/api/threshold")
    def threshold():
        return {"minimum": s().minimum}

    @app.put("/api/threshold")
    def set_threshold(body: Threshold):
        return s().threshold(body.minimum)

    @app.get("/api/runs", response_model=list[views.RunInfo])
    def runs():
        return s().history()

    @app.post("/api/runs", status_code=201)
    def start(body: RunConfig):
        return s().start(body.model_dump())

    @app.get("/api/runs/{rid}", response_model=views.Run)
    def get_run(rid: str):
        return s().get(rid)

    @app.post("/api/runs/{rid}/stop")
    def stop(rid: str):
        return s().command(rid, "stop")

    @app.post("/api/runs/{rid}/continue")
    def resume(rid: str):
        return s().command(rid, "continue")

    @app.get("/api/runs/{rid}/rounds/{number}", response_model=views.Round)
    def round_result(rid: str, number: int):
        for row in s().get(rid)["rounds"]:
            if row["number"] == number:
                return row
        raise HTTPException(404, "No committed model at this round")

    site = Path(__file__).resolve().parents[1] / "frontend" / "dist"

    @app.get("/docs", include_in_schema=False)
    def swagger():
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="Sentinel | Swagger UI",
            swagger_js_url="/swagger/swagger-ui-bundle.js",
            swagger_css_url="/swagger/swagger-ui.css",
            swagger_favicon_url="/swagger/favicon-32x32.png",
        )

    if site.is_dir():
        app.mount("/", StaticFiles(directory=site, html=True), name="dashboard")
    return app


app = create_app()
