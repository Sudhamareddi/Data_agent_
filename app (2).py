"""
Streamlit UI. Same transparency principle as the original project --
every response shows the agent's exploration steps, generated SQL, and
raw underlying data, not just the final answer.

Three data source modes, all running through the exact same agent code:
  - "Payments / fintech demo"     -- 11-table SQLite payments/ops schema.
  - "E-commerce example"          -- 11-table SQLite e-commerce schema.
  - "Upload your own Excel file"  -- any .xlsx/.xls, one table per sheet.

For every mode, the sidebar shows a schema preview (tables, columns,
row counts) before you ask anything -- so you can see what the agent
will be exploring, same as the uploaded-file summary.

Run: streamlit run app.py

Requires GROQ_API_KEY set in Streamlit Cloud's Secrets (Settings ->
Secrets) when deployed, or as a local environment variable when
running on your own machine. It is never entered or shown in the UI.
"""

import os
import streamlit as st
from sqlalchemy import inspect, text
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from db_setup import get_example_engine
from fintech_db_setup import get_fintech_engine
from excel_loader import build_engine_from_excel
from tools import make_tools
from agent_graph import build_agent, SUPPORTED_MODELS, DEFAULT_MODEL

st.set_page_config(page_title="AI Data Analytics Agent (LangGraph)", layout="wide")
st.title("AI Data Analytics Agent — LangGraph Edition")
st.caption(
    "An agent that investigates payments/ops questions — failed transactions, "
    "open disputes, unsettled merchant payouts — without being given the schema "
    "upfront. Autonomous schema discovery, multi-hop joins, repeat-call detection, "
    "malformed-response filtering, and grounded-answer verification."
)


def describe_engine(engine, row_preview: bool = True) -> list[dict]:
    """Inspect any engine and return a summary list, same shape as the
    Excel-upload summary, so every data source gets the same preview."""
    inspector = inspect(engine)
    summary = []
    for table_name in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns(table_name)]
        row_count = None
        if row_preview:
            try:
                with engine.connect() as conn:
                    row_count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            except Exception:
                row_count = None
        summary.append({"table_name": table_name, "rows": row_count, "columns": columns})
    return summary


def show_schema_preview(summary: list[dict], label: str):
    with st.sidebar.expander(f"{label}: {len(summary)} table(s)", expanded=False):
        for s in summary:
            row_txt = f"{s['rows']} rows" if s["rows"] is not None else ""
            cols_txt = ", ".join(s["columns"][:6]) + ("..." if len(s["columns"]) > 6 else "")
            st.write(f"**{s['table_name']}** ({row_txt}) — {cols_txt}")


# ---------------- Sidebar: data source ----------------
st.sidebar.header("Data source")
source_mode = st.sidebar.radio(
    "Choose a database",
    ["Payments / fintech demo", "E-commerce example", "Upload your own Excel file"],
    help="The payments demo mirrors a real support/ops investigation over transactions, refunds, disputes, and settlements.",
)

if source_mode == "Payments / fintech demo":
    engine = get_fintech_engine()
    show_schema_preview(describe_engine(engine), "Payments / fintech demo")
elif source_mode == "E-commerce example":
    engine = get_example_engine()
    show_schema_preview(describe_engine(engine), "E-commerce example")
else:
    uploaded = st.sidebar.file_uploader("Upload .xlsx / .xls", type=["xlsx", "xls"])
    if uploaded is None:
        st.info("Upload an Excel file in the sidebar to begin, or switch back to an example database.")
        st.stop()

    if st.session_state.get("_uploaded_name") != uploaded.name:
        with st.spinner("Reading workbook and building schema..."):
            engine, uploaded_summary = build_engine_from_excel(uploaded)
        st.session_state["_engine"] = engine
        st.session_state["_uploaded_summary"] = uploaded_summary
        st.session_state["_uploaded_name"] = uploaded.name
        # New file -> reset conversation, old schema no longer applies.
        st.session_state["state"] = {"messages": [], "tool_call_log": [], "schema_cache": {}, "verify_attempts": 0}
        st.session_state["history"] = []

    engine = st.session_state["_engine"]
    show_schema_preview(st.session_state.get("_uploaded_summary", []), "Uploaded file")

# ---------------- Sidebar: model (no key input -- pulled from secrets) ----------------
# Only currently-supported Groq models are offered. llama-3.3-70b-versatile
# was deprecated by Groq on 2026-06-17 and fully decommissioned on
# 2026-08-16 -- it is no longer served, so it has been removed from this
# list rather than left in as a silent trap. See agent_graph.SUPPORTED_MODELS.
model_name = st.sidebar.selectbox("Model", SUPPORTED_MODELS, index=SUPPORTED_MODELS.index(DEFAULT_MODEL))
st.sidebar.caption(
    "Only currently-supported Groq models are listed. If a model is "
    "deprecated in the future, remove it from `SUPPORTED_MODELS` in "
    "agent_graph.py rather than leaving it selectable."
)


def _get_api_key() -> str:
    try:
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
    except Exception:
        pass  # no secrets.toml at all (e.g. local run, Colab) -- fall through
    return os.getenv("GROQ_API_KEY", "")


api_key = _get_api_key()
if not api_key:
    st.sidebar.error(
        "GROQ_API_KEY isn't configured. On Streamlit Cloud: Settings -> "
        "Secrets -> add GROQ_API_KEY. Locally: set it as an environment variable."
    )

# ---------------- Conversation state ----------------
if "state" not in st.session_state:
    st.session_state.state = {"messages": [], "tool_call_log": [], "schema_cache": {}, "verify_attempts": 0}
if "history" not in st.session_state:
    st.session_state.history = []

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.write(turn["content"])
        if turn.get("trace"):
            with st.expander("Exploration steps, SQL, and raw data"):
                st.code(turn["trace"], language="json")

prompt = st.chat_input("Ask a question about the database...")

if prompt:
    if not api_key:
        st.error("GROQ_API_KEY isn't configured — see the sidebar message above.")
        st.stop()

    with st.chat_message("user"):
        st.write(prompt)
    st.session_state.history.append({"role": "user", "content": prompt})

    tools = make_tools(engine)

    st.session_state.state["messages"] = list(st.session_state.state["messages"]) + [HumanMessage(content=prompt)]
    st.session_state.state["verify_attempts"] = 0

    # --- Error handling: a bad/deprecated/rate-limited model call must
    # never crash the whole app. Try the selected model; on failure, fall
    # back once to DEFAULT_MODEL and tell the user what happened instead
    # of showing a raw traceback. ---
    result_state = None
    error_message = None
    used_model = model_name

    with st.spinner("Exploring schema and reasoning..."):
        try:
            agent = build_agent(tools, model_name=model_name, api_key=api_key)
            result_state = agent.invoke(st.session_state.state)
        except Exception as e:
            first_error = str(e)
            if model_name != DEFAULT_MODEL:
                # Retry once with the known-good default before giving up.
                try:
                    agent = build_agent(tools, model_name=DEFAULT_MODEL, api_key=api_key)
                    result_state = agent.invoke(st.session_state.state)
                    used_model = DEFAULT_MODEL
                    error_message = (
                        f"'{model_name}' failed ({first_error[:200]}). "
                        f"Fell back to '{DEFAULT_MODEL}' for this response."
                    )
                except Exception as e2:
                    error_message = f"Both '{model_name}' and the fallback '{DEFAULT_MODEL}' failed: {str(e2)[:300]}"
            else:
                error_message = f"The model call failed: {first_error[:300]}"

    if result_state is None:
        with st.chat_message("assistant"):
            st.error(
                "Sorry — I couldn't get a response from the model. "
                f"{error_message}\n\nThis is usually a temporary API issue, an "
                "invalid/expired key, or a deprecated model name. Try again, "
                "or pick a different model from the sidebar."
            )
        st.session_state.history.append({
            "role": "assistant",
            "content": f"[Error] {error_message}",
            "trace": "",
        })
        st.stop()

    if error_message:
        st.sidebar.warning(error_message)

    st.session_state.state = result_state

    trace_lines = []
    final_answer = ""
    for m in result_state["messages"]:
        if isinstance(m, ToolMessage):
            trace_lines.append(m.content)
        elif isinstance(m, AIMessage) and m.content:
            final_answer = m.content

    with st.chat_message("assistant"):
        if used_model != model_name:
            st.caption(f"(Answered using {used_model} after {model_name} failed.)")
        st.write(final_answer)
        with st.expander("Exploration steps, SQL, and raw data"):
            st.code("\n".join(trace_lines), language="json")

    st.session_state.history.append({
        "role": "assistant",
        "content": final_answer,
        "trace": "\n".join(trace_lines),
    })
