import os
import pandas as pd
import streamlit as st
import psycopg2
from datetime import datetime

st.set_page_config(page_title="Donut Land Inventory Dashboard", layout="wide")

st.markdown(
    """
    <style>
    div[data-testid="column"] {
        background-color: #fffafc;
        border: 1px solid #f1e1eb;
        border-radius: 12px;
        padding: 15px;
        margin: 8px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .item-title {
        font-size: 18px;
        font-weight: 700;
        color: #c94d94;
        margin-bottom: 4px;
    }
    .item-sub {
        font-size: 13px;
        color: #6c757d;
        margin-bottom: 10px;
    }
    .stNumberInput input {
        text-align: center !important;
        font-weight: 600 !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ---------- Database connection ----------
def get_conn():
    db_url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        st.error("❌ Missing DATABASE_URL secret in Streamlit settings.")
        st.stop()
    if "sslmode=" not in db_url:
        db_url += "?sslmode=require"
    return psycopg2.connect(db_url)

try:
    conn = get_conn()
except Exception as e:
    st.error("Could not connect to database.")
    st.exception(e)
    st.stop()

# ---------- Load data ----------
@st.cache_data(ttl=30)
def load_data(connection):
    query = """
      with onhand as (
        select ingredient_id, sum(case when type='in' then qty else -qty end) as on_hand
        from inventory_txns group by ingredient_id
      )
      select i.id, i.name, i.unit, i.vendor, i.area,
             coalesce(o.on_hand,0) as on_hand
      from ingredients i
      left join onhand o on o.ingredient_id = i.id
      order by i.area, i.name;
    """
    return pd.read_sql(query, connection)

data = load_data(conn)
areas = sorted(data["area"].dropna().unique())

if not len(areas):
    st.warning("No areas found. Add 'area' values to ingredients in Supabase.")
    st.stop()

# ---------- Header ----------
area = st.sidebar.selectbox("📍 Choose an Area", areas, index=0)
st.header(f"🍩 {area} — Inventory Count")

df = data[data["area"] == area].copy()

col1, col2, col3 = st.columns([2, 1, 1])
col1.metric("Items", len(df))
col2.metric("Adjusted this session", "0")
col3.metric("Time", datetime.now().strftime("%-I:%M %p"))

search = st.text_input("🔍 Search", placeholder=f"Search {area}…").strip().lower()
if search:
    df = df[df["name"].str.lower().str.contains(search)]

# ---------- Initialize session counts ----------
if "counts" not in st.session_state:
    st.session_state["counts"] = {}

counts = st.session_state["counts"]

# ---------- Layout ----------
df = df.reset_index(drop=True)

for i, row in df.iterrows():
    rid = row.id
    name = row.name or "Unnamed Ingredient"
    counts.setdefault(rid, float(row.on_hand))

    with st.container():
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown(f"<div class='item-title'>{name}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='item-sub'>Unit: {row.unit or '-'} • Vendor: {row.vendor or '-'} • Current: {row.on_hand:.2f}</div>",
                unsafe_allow_html=True
            )
        with c2:
            val = st.number_input(
                "On Hand",
                key=f"{area}_{rid}",
                value=float(counts[rid]),
                step=0.5,
                label_visibility="collapsed"
            )
            counts[rid] = val
        with c3:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button("💾 Save", key=f"save_{rid}"):
                try:
                    with conn, conn.cursor() as cur:
                        cur.execute("""
                            insert into inventory_txns (ingredient_id, type, qty, source)
                            values (%s, 'in', %s, 'manual adjustment');
                        """, (rid, counts[rid]))
                    st.success(f"{name} updated!")
                except Exception as e:
                    st.error("Save failed.")
                    st.exception(e)
        st.markdown("---")
