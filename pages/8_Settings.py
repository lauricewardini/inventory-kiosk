import streamlit as st
import pandas as pd
from lib.inv_helpers import get_conn

st.set_page_config(page_title="Settings", layout="wide")
st.title("⚙️ Settings — Vendors, Areas, Usage & Par")

conn = get_conn()
df = pd.read_sql("""
  select id, name, unit, vendor, area,
         coalesce(weekly_usage,0) as weekly_usage,
         coalesce(par,0) as par_override
  from ingredients
  order by name;
""", conn)

st.caption("Edit fields and click **Save Changes**. Par override: leave 0 to use formula (weekly/7 × 11).")

edited = st.data_editor(
    df,
    column_config={
        "name": "Ingredient",
        "unit": "Unit",
        "vendor": st.column_config.TextColumn(help="e.g., Bakemark, Dawn"),
        "area": st.column_config.TextColumn(help="e.g., Kitchen, Utility Room"),
        "weekly_usage": st.column_config.NumberColumn(format="%.2f", help="Weekly usage → app uses weekly/7 × 11 for par"),
    },
    hide_index=True,
    use_container_width=True
)

if st.button("💾 Save Changes", type="primary"):
    # Compare and write diffs
    changes = 0
    with conn, conn.cursor() as cur:
        for _, row in edited.iterrows():
            cur.execute("""
              update ingredients
                 set vendor = %s,
                     area = %s,
                     weekly_usage = %s,
                     par = %s
               where id = %s
            """, (row["vendor"] or None,
                  row["area"] or None,
                  float(row["weekly_usage"] or 0),
                  float(row["par_override"] or 0),
                  row["id"]))
            changes += 1
    st.success(f"Saved {changes} rows.")

