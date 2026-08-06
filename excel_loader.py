"""
Converts an uploaded Excel file into a fresh SQLite database -- one
table per sheet -- so the exact same agent (same tools, same graph,
same safeguards) can explore it, with zero code path difference from
the example database.
"""
import os
import re
import tempfile
import pandas as pd
from sqlalchemy import create_engine

_NAME_RE = re.compile(r"[^0-9a-zA-Z_]+")


def _clean_name(name: str) -> str:
    """Make a sheet/column name safe as a SQL identifier."""
    name = str(name).strip()
    name = _NAME_RE.sub("_", name)
    if not name or name[0].isdigit():
        name = f"col_{name}"
    return name.lower()


def build_engine_from_excel(uploaded_file):
    """
    uploaded_file: a Streamlit UploadedFile (or any file-like object)
    containing an .xlsx/.xls workbook.

    Returns: (engine, sheet_summary) where sheet_summary is a list of
    dicts describing what was loaded, for display in the UI.
    """
    xls = pd.ExcelFile(uploaded_file)

    # Fresh, isolated SQLite file per upload so concurrent users /
    # repeated uploads never collide.
    tmp_dir = tempfile.mkdtemp(prefix="uploaded_db_")
    db_path = os.path.join(tmp_dir, "uploaded.db")
    engine = create_engine(f"sqlite:///{db_path}")

    summary = []
    seen_table_names = set()

    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        if df.empty:
            continue

        # Clean column names so the agent's generated SQL doesn't choke
        # on spaces/special characters.
        df.columns = [_clean_name(c) for c in df.columns]

        table_name = _clean_name(sheet_name)
        base_name = table_name
        i = 1
        while table_name in seen_table_names:
            table_name = f"{base_name}_{i}"
            i += 1
        seen_table_names.add(table_name)

        df.to_sql(table_name, engine, index=False, if_exists="replace")
        summary.append({
            "sheet": sheet_name,
            "table_name": table_name,
            "rows": len(df),
            "columns": list(df.columns),
        })

    if not summary:
        raise ValueError("No non-empty sheets found in the uploaded file.")

    return engine, summary
