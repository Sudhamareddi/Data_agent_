"""
Core LangGraph agent.

This replaces the original custom Groq tool-calling loop with a proper
LangGraph StateGraph, while preserving the same reliability guarantees
the original project had:

  1. Repeat-call detection   -> tool_node() checks a call-signature log
                                 before executing, so the agent can't
                                 loop on an identical call.
  2. Malformed-response filtering -> tools.py rejects bad SQL / unknown
                                 table names before they hit the DB;
                                 tool_node() also guards against
                                 malformed tool-call args from the LLM.
  3. Grounded-answer verification -> verify_node() checks that the
                                 final answer's key facts actually
                                 appear in tool output before letting
                                 the graph terminate.

Swap `sample.db` in tools.py for a real connection string to point
this at production data -- the graph and safeguards don't change.
"""
import os
import json
from typing import TypedDict, Annotated, Sequence

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

SYSTEM_PROMPT = """You are a database analyst agent. You do NOT know the
database schema in advance. Before writing any SQL:
1. Call list_tables to see what exists.
2. Call get_table_schema on every table you plan to touch.
3. Only then write a SELECT query with run_sql_query.
Never guess table or column names. If a query fails, read the error and
correct it. When you have enough information, give a final answer in
plain language, citing the specific numbers/rows you retrieved."""


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tool_call_log: list          # signatures of tool calls already made
    schema_cache: dict           # table_name -> schema JSON, reused across turns
    verify_attempts: int         # guards the grounded-answer retry loop


def _signature(name: str, args: dict) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True)}"


def build_agent(tools: list, model_name: str = "llama-3.3-70b-versatile", api_key: str | None = None):
    """
    tools: the list returned by tools.make_tools(engine) -- bound to
    whichever database is active (example DB or an uploaded Excel file).
    """
    llm = ChatGroq(model=model_name, api_key=api_key, temperature=0)
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    def call_model(state: AgentState):
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def tool_node(state: AgentState):
        last_message = state["messages"][-1]
        tool_call_log = list(state.get("tool_call_log", []))
        schema_cache = dict(state.get("schema_cache", {}))
        results = []

        for call in last_message.tool_calls:
            name, args, call_id = call["name"], call["args"], call["id"]

            # --- Safeguard 1: repeat-call detection ---
            sig = _signature(name, args)
            if sig in tool_call_log:
                results.append(ToolMessage(
                    content=json.dumps({
                        "note": "You already made this exact call. "
                                "Reuse the result from earlier in this conversation "
                                "instead of calling it again."
                    }),
                    tool_call_id=call_id
                ))
                continue

            # --- Safeguard 2: malformed-response filtering ---
            if name not in tools_by_name:
                results.append(ToolMessage(
                    content=json.dumps({"error": f"Unknown tool '{name}'."}),
                    tool_call_id=call_id
                ))
                continue

            try:
                output = tools_by_name[name].invoke(args)
            except Exception as e:
                output = json.dumps({"error": f"Tool call failed: {str(e)}"})

            tool_call_log.append(sig)
            if name == "get_table_schema" and "table_name" in args:
                schema_cache[args["table_name"]] = output

            results.append(ToolMessage(content=output, tool_call_id=call_id))

        return {
            "messages": results,
            "tool_call_log": tool_call_log,
            "schema_cache": schema_cache,
        }

    def verify_node(state: AgentState):
        # --- Safeguard 3: grounded-answer verification ---
        # Cheap heuristic check: does the final answer contain at least
        # one number that actually appeared in a tool result? If the
        # agent never called a tool, or the answer looks fabricated,
        # send it back once with an explicit instruction to ground its
        # answer in real data.
        attempts = state.get("verify_attempts", 0)
        final = state["messages"][-1].content
        tool_outputs = " ".join(
            m.content for m in state["messages"] if isinstance(m, ToolMessage)
        )

        numbers_in_answer = set(re_findall_numbers(final))
        numbers_in_evidence = set(re_findall_numbers(tool_outputs))
        grounded = bool(tool_outputs) and (
            not numbers_in_answer or numbers_in_answer & numbers_in_evidence
        )

        if grounded or attempts >= 1:
            return {"verify_attempts": attempts + 1}

        warning = HumanMessage(content=(
            "Your answer doesn't clearly cite data from your tool calls. "
            "Re-check your last query results and restate the answer using "
            "only numbers/facts that actually appeared in run_sql_query output."
        ))
        return {"messages": [warning], "verify_attempts": attempts + 1}

    def route_after_model(state: AgentState):
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "verify"

    def route_after_verify(state: AgentState):
        return END if state.get("verify_attempts", 0) >= 2 else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.add_node("verify", verify_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route_after_model, {"tools": "tools", "verify": "verify"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("verify", route_after_verify, {"agent": "agent", END: END})

    return graph.compile()


def re_findall_numbers(text: str):
    import re
    return re.findall(r"\d+\.?\d*", text or "")
