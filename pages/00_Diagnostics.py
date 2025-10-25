import os, socket
import psycopg2
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Diagnostics", layout="wide")
st.title("🧪 Diagnostics")

# 1) Read secret and show parsed host
db_url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
st.write("Has DATABASE_URL:", "✅" if db_url else "❌")
if not db_url:
    st.stop()

st.code(db_url, language="bash")
try:
    host = db_url.split("@",1)[1].split(":",1)[0]
    st.write("Host:", host)
    st.write("Host resolves to:", socket.gethostbyname(host))
except Exception as e:
    st.warning(f"Couldn't parse/resolve host: {e}")

if "sslmode=" not in db_url:
    db_url = f"{db_url}?sslmode=require"

# 2) Connect and show errors if any
try:
    conn = psycopg2.connect(db_url)
    st.success("Connected to Supabase/Postgres ✅")
except Exception as e:
    st.error("❌ Could not connect. Check host (must start with db.), user/password, or SSL.")
    st.exception(e)
    st.stop()

# 3) Show tables present
try:
    tables = pd.read_sql("""
      select table_name
      from information_schema.tables
      where table_schema='public'
      order by table_name;
    """, conn)
    st.subheader("Public tables")
    st.dataframe(tables, use_container_width=True, hide_index=True)
except Exception as e:
    st.error("Failed to list tables")
    st.exception(e)

# 4) Sample rows from key tables
def show(title, sql):
    st.subheader(title)
    try:
        df = pd.read_sql(sql, conn)
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Query failed: {sql}")
        st.exception(e)

show("ingredients (up to 10 rows)", "select * from ingredients limit 10;")
show("inventory_txns (up to 10 rows)", "select * from inventory_txns limit 10;")
show("Items by Area", """
  select coalesce(area,'(null)') area, count(*) items
  from ingredients
  group by 1 order by 1;
""")
