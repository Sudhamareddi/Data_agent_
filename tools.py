"""
The three tools the agent uses to explore an unfamiliar schema before
answering. Refactored into a factory (`make_tools`) so the exact same
tool logic works whether the underlying data is the bundled example
SQLite DB or a SQLite DB built on the fly from an uploaded Excel file --
there is zero behavioral difference between the two modes.
"""
import json
import re
from sqlalchemy import inspect, text
from langchain_core.tools import tool

# Cap how many rows we ever return to the model -- keeps context small
# and prevents a runaway "SELECT *" from blowing up the conversation.
MAX_ROWS = 25

_WRITE_KEYWORDS = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate)\b", re.IGNORECASE)


def make_tools(engine):
    """Build the three agent tools bound to a specific SQLAlchemy engine."""

    @tool
    def list_tables() -> str:
        """List every table available in the database. Always call this
        first when you don't yet know the schema."""
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        return json.dumps({"tables": tables})

    @tool
    def get_table_schema(table_name: str) -> str:
        """Get the columns, types, and foreign-key relationships for a
        specific table. Call this before writing SQL that touches a
        table you haven't inspected yet."""
        inspector = inspect(engine)
        valid_tables = inspector.get_table_names()
        if table_name not in valid_tables:
            # Malformed / hallucinated table name -- structured error
            # so the agent can self-correct instead of the tool
            # crashing or silently returning nothing.
            return json.dumps({
                "error": f"'{table_name}' is not a real table.",
                "valid_tables": valid_tables
            })

        columns = inspector.get_columns(table_name)
        fks = inspector.get_foreign_keys(table_name)
        return json.dumps({
            "table": table_name,
            "columns": [{"name": c["name"], "type": str(c["type"])} for c in columns],
            "foreign_keys": [
                {"column": fk["constrained_columns"], "references": f"{fk['referred_table']}.{fk['referred_columns']}"}
                for fk in fks
            ]
        })

    @tool
    def run_sql_query(query: str) -> str:
        """Execute a read-only SQL SELECT query against the database and
        return the results. Only use table/column names you have
        already confirmed via get_table_schema."""
        # Malformed-response filtering: reject anything that isn't a
        # read-only SELECT before it ever touches the database.
        if not query.strip().lower().startswith("select"):
            return json.dumps({"error": "Only SELECT queries are allowed."})
        if _WRITE_KEYWORDS.search(query):
            return json.dumps({"error": "Query contains a disallowed write keyword."})

        try:
            with engine.connect() as conn:
                result = conn.execute(text(query))
                rows = [dict(r._mapping) for r in result.fetchmany(MAX_ROWS)]
            return json.dumps({"row_count": len(rows), "rows": rows})
        except Exception as e:
            # Surface the real DB error back to the agent so it can
            # retry with corrected SQL, instead of the whole run crashing.
            return json.dumps({"error": f"SQL execution failed: {str(e)}"})

    return [list_tables, get_table_schema, run_sql_query]
