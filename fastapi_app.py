"""
FastAPI wrapper around the LangGraph data-analytics agent.

This exposes the exact same agent used by app.py (Streamlit) as a REST
API, so it can be called from any client -- curl, Postman, another
service -- not just the Streamlit UI. No agent logic changes: this file
only adds a web layer on top of agent_graph.build_agent() and
tools.make_tools(), which are imported unchanged.

Run locally:
    export GROQ_API_KEY=your_key_here
    uvicorn fastapi_app:app --reload

Then:
    curl -X POST http://127.0.0.1:8000/ask \
        -H "Content-Type: application/json" \
        -d '{"question": "Which merchants have pending settlements?", "source": "fintech"}'

Docs (auto-generated): http://127.0.0.1:8000/docs
"""

import os
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from db_setup import get_example_engine
from fintech_db_setup import get_fintech_engine
from tools import make_tools
from agent_graph import build_agent, SUPPORTED_MODELS, DEFAULT_MODEL

app = FastAPI(
    title="AI Data Analytics Agent API",
    description=(
        "Investigates payments/ops questions (failed transactions, disputes, "
        "settlements) with zero schema given upfront. Built on LangGraph, "
        "with repeat-call detection, malformed-response filtering, and "
        "grounded-answer verification as real logic, not prompting."
    ),
    version="1.0.0",
)

# Loosen this to your actual frontend origin(s) before deploying publicly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store: conversation_id -> agent state.
# Fine for a demo/portfolio API; swap for Redis or a DB table if this
# needs to survive process restarts or run across multiple workers.
_SESSIONS: dict[str, dict] = {}


def _get_api_key() -> str:
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is not configured on the server.",
        )
    return key


def _get_engine(source: str):
    if source == "fintech":
        return get_fintech_engine()
    if source == "ecommerce":
        return get_example_engine()
    raise HTTPException(status_code=400, detail=f"Unknown source '{source}'. Use 'fintech' or 'ecommerce'.")


class AskRequest(BaseModel):
    question: str = Field(..., description="Natural-language question about the database.")
    source: Literal["fintech", "ecommerce"] = Field(
        default="fintech", description="Which demo schema to query."
    )
    model: str = Field(default=DEFAULT_MODEL, description=f"One of {SUPPORTED_MODELS}.")
    conversation_id: str | None = Field(
        default=None,
        description="Reuse an existing conversation_id to continue a multi-turn session. "
                    "Omit to start a new one.",
    )


class AskResponse(BaseModel):
    conversation_id: str
    answer: str
    trace: list[str] = Field(description="Raw tool call results, in order -- the SQL run and rows returned.")
    model_used: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest):
    if payload.model not in SUPPORTED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model '{payload.model}'. Choose one of {SUPPORTED_MODELS}.",
        )

    api_key = _get_api_key()
    engine = _get_engine(payload.source)
    tools = make_tools(engine)

    conversation_id = payload.conversation_id or str(uuid.uuid4())
    state = _SESSIONS.get(conversation_id, {
        "messages": [],
        "tool_call_log": [],
        "schema_cache": {},
        "verify_attempts": 0,
    })

    state["messages"] = list(state["messages"]) + [HumanMessage(content=payload.question)]
    state["verify_attempts"] = 0

    used_model = payload.model
    try:
        agent = build_agent(tools, model_name=payload.model, api_key=api_key)
        result_state = agent.invoke(state)
    except Exception as first_error:
        if payload.model != DEFAULT_MODEL:
            try:
                agent = build_agent(tools, model_name=DEFAULT_MODEL, api_key=api_key)
                result_state = agent.invoke(state)
                used_model = DEFAULT_MODEL
            except Exception as second_error:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Both '{payload.model}' and fallback '{DEFAULT_MODEL}' failed. "
                        f"First error: {str(first_error)[:200]} | Second error: {str(second_error)[:200]}"
                    ),
                )
        else:
            raise HTTPException(status_code=502, detail=f"Model call failed: {str(first_error)[:300]}")

    _SESSIONS[conversation_id] = result_state

    trace = [m.content for m in result_state["messages"] if isinstance(m, ToolMessage)]
    final_answer = ""
    for m in result_state["messages"]:
        if isinstance(m, AIMessage) and m.content:
            final_answer = m.content

    return AskResponse(
        conversation_id=conversation_id,
        answer=final_answer,
        trace=trace,
        model_used=used_model,
    )


@app.delete("/conversations/{conversation_id}")
def clear_conversation(conversation_id: str):
    """Drop a conversation's state -- start fresh on the next /ask with the same id, or just stop reusing it."""
    _SESSIONS.pop(conversation_id, None)
    return {"cleared": conversation_id}
