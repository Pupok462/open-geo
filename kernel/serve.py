"""Local visual board. No account, no SaaS."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from kernel import collect, store

WEB = Path(__file__).resolve().parent / "web"

app = FastAPI(title="kernel studio")


class StartIn(BaseModel):
    url: str
    brand: str = ""
    geo: str = "ru"
    language: str = "ru"
    gate: str = "human"
    n: int = 12


class RoundIn(BaseModel):
    slug: str
    n: int = Field(default=12, ge=1, le=40)


class DecideIn(BaseModel):
    slug: str
    question_id: str
    status: str


class GateIn(BaseModel):
    slug: str
    gate: str


def _payload(kernel) -> dict:
    data = kernel.model_dump()
    data["counts"] = {
        "inbox": len(kernel.by_status("inbox")),
        "accepted": len(kernel.by_status("accepted")),
        "rejected": len(kernel.by_status("rejected")),
        "deferred": len(kernel.by_status("deferred")),
    }
    return data


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/board/{slug}")
def board(slug: str):
    try:
        return _payload(store.load(slug))
    except FileNotFoundError as exc:
        raise HTTPException(404, f"no kernel {slug}") from exc


@app.post("/api/start")
def start(body: StartIn):
    kernel = collect.start(
        body.url,
        brand=body.brand or None,
        geo=body.geo,
        language=body.language,
        gate=body.gate,
    )
    kernel = collect.round(kernel, n=body.n)
    return _payload(kernel)


@app.post("/api/round")
def grow(body: RoundIn):
    try:
        kernel = store.load(body.slug)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"no kernel {body.slug}") from exc
    kernel = collect.round(kernel, n=body.n)
    return _payload(kernel)


@app.post("/api/decide")
def decide(body: DecideIn):
    try:
        kernel = store.load(body.slug)
        kernel = collect.decide(kernel, body.question_id, body.status)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"no kernel {body.slug}") from exc
    except KeyError as exc:
        raise HTTPException(404, f"no question {body.question_id}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _payload(kernel)


@app.post("/api/gate")
def set_gate(body: GateIn):
    if body.gate not in {"human", "auto"}:
        raise HTTPException(400, "gate must be human or auto")
    try:
        kernel = store.load(body.slug)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"no kernel {body.slug}") from exc
    kernel.gate = body.gate  # type: ignore[assignment]
    store.save(kernel)
    return _payload(kernel)


def run(host: str = "127.0.0.1", port: int = 8099, open_browser: bool = False) -> None:
    import uvicorn

    if open_browser:
        webbrowser.open(f"http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="info")
