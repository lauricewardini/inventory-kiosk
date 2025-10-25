import os, pandas as pd, streamlit as st
import psycopg2

st.set_page_config(page_title="Diagnostics", layout="wide")
st.title("🧪 Diagnostics")

# Read secret
db_url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
st.write("Has DATABASE_URL:", "✅" if db_url else "❌")
if not db_url:
    st.stop()
if "sslmode=" not in db_url:
    db_url = f"{db_url}?sslmode=require"

# Connect
try:
    conn = psycopg2.connect(db_url)
    st.success("Connected to Supabase/Postgres.")
except Exception as e:
    st.error("Could not connect.")
    st.exception(e)
    st.stop()

def try_show(title, sql):
    st.subheader(title)
    try:
        df = pd.read_sql(sql, conn)
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Query failed: {sql}")
        st.exception(e)

# Show table samples
try_show("ingredients (up to 10 rows)", "select * from ingredients limit 10;")
try_show("inventory_txns (up to 10 rows)", "select * from inventory_txns limit 10;")

# Columns existence
st.subheader("Column check")
try_show("ingredients columns", """
    select column_name, data_type
    from information_schema.columns
    where table_schema='public' and table_name='ingredients'
    order by 1;
""")

# Areas summary (helps spot mismatches)
try_show("Items by Area", """
    select coalesce(area,'(null)') as area, count(*) as items
    from ingredients
    group by 1 order by 1;
""")
