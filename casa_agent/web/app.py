"""FastAPI app: chat endpoint + static UI.

Run:  uvicorn casa_agent.web.app:app --reload
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import config
from ..agent import chat_turn
from ..models import SearchParams, SearchResult

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="casa-agent", version="0.1.0")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# In-memory sessions: {session_id: {"messages": [...], "params": SearchParams|None}}
_sessions: dict[str, dict] = {}


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    sources: list[str] | None = None


class ChatResponse(BaseModel):
    session_id: str
    result: SearchResult


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "llm": bool(config.ANTHROPIC_API_KEY),
        "sources": config.SOURCES,
        "idealista_configured": bool(config.IDEALISTA_API_KEY),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "Empty message")
    sid = req.session_id or uuid.uuid4().hex
    sess = _sessions.setdefault(sid, {"messages": [], "params": None})
    sess["messages"].append({"role": "user", "content": req.message})

    result = await chat_turn(sess["messages"], sess["params"], req.sources, session_id=sid)

    sess["params"] = result.params
    # Keep the assistant's turn short in history so the next intake call stays cheap
    sess["messages"].append({"role": "assistant", "content": f"Searched with: {result.params.summary()}. Found {result.matching} matches."})
    return ChatResponse(session_id=sid, result=result)


@app.post("/api/reset")
async def reset(session_id: str):
    _sessions.pop(session_id, None)
    return {"ok": True}
