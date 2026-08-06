"""
Streamlit UI. Same transparency principle as the original project --
every response shows the agent's exploration steps, generated SQL, and
raw underlying data, not just the final answer.

Two data source modes, both running through the exact same agent code:
  - "Example database" -- the bundled 11-table SQLite e-commerce DB.
  - "Upload your own Excel file" -- any .xlsx/.xls, one table per sheet.

Run: streamlit run app.py
Requires GROQ_API_KEY set as an environment variable or entered in the sidebar.
"""
import os
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from db_setup import get_example_engine
from fintech_db_setup import get_fintech_engine
from excel_loader import build_engine_from_excel
from tools import make_tools
from agent_graph import build_agent

st.set_page_config(page_title="AI Data Analytics Agent (LangGraph)", layout="wide")

st.title("AI Data Analytics Agent — LangGraph Edition")
st.caption(
    "An agent that investigates payments/ops questions — failed transactions, "
    "open disputes, unsettled merchant payouts — without being given the schema "
    "upfront. Autonomous schema discovery, multi-hop joins, repeat-call detection, "
    "malformed-response filtering, and grounded-answer verification."
)

# ---------------- Sidebar: data source + model ----------------
st.sidebar.header("Data source")
source_mode = st.sidebar.radio(
    "Choose a database",
    ["Payments / fintech demo", "E-commerce example", "Upload your own Excel file"],
    help="The payments demo mirrors a real support/ops investigation over transactions, refunds, disputes, and settlements.",
)

uploaded_summary = None
if source_mode == "Payments / fintech demo":
    engine = get_fintech_engine()
    st.sidebar.caption(
        "11 tables: merchants, customers, transactions, refunds, disputes, "
        "settlements, subscriptions, invoices, webhook events, support tickets."
    )
elif source_mode == "E-commerce example":
    engine = get_example_engine()
else:
    uploaded = st.sidebar.file_uploader("Upload .xlsx / .xls", type=["xlsx", "xls"])
    if uploaded is None:
        st.info("Upload an Excel file in the sidebar to begin, or switch back to the example database.")
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
    uploaded_summary = st.session_state.get("_uploaded_summary")

if uploaded_summary:
    with st.sidebar.expander(f"Loaded {len(uploaded_summary)} sheet(s) as tables"):
        for s in uploaded_summary:
            st.write(f"**{s['table_name']}** ({s['rows']} rows) — {', '.join(s['columns'][:6])}{'...' if len(s['columns']) > 6 else ''}")

api_key = st.sidebar.text_input("GROQ_API_KEY", type="password", value=os.getenv("GROQ_API_KEY", ""))
model_name = st.sidebar.selectbox(
    "Model", ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
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
        st.error("Enter your GROQ_API_KEY in the sidebar first.")
        st.stop()

    with st.chat_message("user"):
        st.write(prompt)
    st.session_state.history.append({"role": "user", "content": prompt})

    tools = make_tools(engine)
    agent = build_agent(tools, model_name=model_name, api_key=api_key)
    st.session_state.state["messages"] = list(st.session_state.state["messages"]) + [HumanMessage(content=prompt)]
    st.session_state.state["verify_attempts"] = 0

    with st.spinner("Exploring schema and reasoning..."):
        result_state = agent.invoke(st.session_state.state)

    st.session_state.state = result_state

    trace_lines = []
    final_answer = ""
    for m in result_state["messages"]:
        if isinstance(m, ToolMessage):
            trace_lines.append(m.content)
        elif isinstance(m, AIMessage) and m.content:
            final_answer = m.content

    with st.chat_message("assistant"):
        st.write(final_answer)
        with st.expander("Exploration steps, SQL, and raw data"):
            st.code("\n".join(trace_lines), language="json")

    st.session_state.history.append({
        "role": "assistant",
        "content": final_answer,
        "trace": "\n".join(trace_lines),
    })
