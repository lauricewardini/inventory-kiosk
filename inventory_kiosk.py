import os
from datetime import datetime

import pandas as pd
import psycopg2
import streamlit as st

# -------------------- Page setup --------------------
st.set_page_config(page_title="Donut Land Inventory Dashboard", layout="wide")

st.markdown(
    """
    <style>
    div[data-testid="column"] {
        background-color: #fffafc;
        border: 1px solid #f1e1eb;
        border-radius: 12px;
        padding: 14px;
        margin: 8px 6px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .item-title { font-size: 18px; font-weight: 700; color: #c94d94; margin-bottom: 4px; }
    .item-sub   { font-size: 13px; color: #6c757d; margin-bottom: 10px; }
    .stNumberInput input { text-align: center !important; font-weight: 600 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------- DB connection --------------------
def get_conn():
    db_url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        st.error("Missing DATABASE_URL secret in Streamlit settings.")
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

# -------------------- Data access --------------------
@st.cache_data(ttl=30)
def load_items(connection):
    sql = """
        with onhand as (
            select ingredient_id,
                   sum(case when type='in' then qty else -qty end) as on_hand
            from inventory_txns
            group by ingredient_id
        )
        select i.id,
               i.short_code,
               i.name,
               i.vendor,
               i.area,
               coalesce(o.on_hand, 0) as on_hand
        from ingredients i
        left join onhand o
          on o.ingredient_id = i.id
        order by i.area, i.name;
    """
    return pd.read_sql(sql, connection)

def save_absolute_count(connection, ingredient_id: str, new_on_hand: float):
    # Insert the minimal delta needed to reach the absolute "new_on_hand" amount
    sql = """
        with current as (
            select coalesce(sum(case when type='in' then qty else -qty end),0) as on_hand
            from inventory_txns
            where ingredient_id = %s
        )
        insert into inventory_txns (ingredient_id, type, qty, source)
        select %s,
               case when %s >= on_hand then 'in' else 'out' end,
               abs(%s - on_hand),
               'manual adjustment'
        from current
        where %s <> on_hand;
    """
    with connection, connection.cursor() as cur:
        cur.execute(sql, (ingredient_id, ingredient_id, new_on_hand, new_on_hand, new_on_hand))

# -------------------- Load + basic UI --------------------
data = load_items(conn)
areas = sorted(data["area"].dropna().unique())

if not areas:
    st.warning("No areas found. Add 'area' to ingredients in Supabase, then refresh.")
    st.stop()

area = st.sidebar.selectbox("📍 Choose an Area", areas, index=0)
st.header(f"🍩 {area} — Inventory Count")

df = data[data["area"] == area].copy().reset_index(drop=True)

m1, m2, m3 = st.columns([2, 1, 1])
m1.metric("Items", len(df))
m2.metric("Adjusted this session", "0")
m3.metric("Time", datetime.now().strftime("%-I:%M %p"))

search = st.text_input("🔍 Search", placeholder=f"Search {area}…").strip().lower()
if search:
    df = df[df["name"].str.lower().str.contains(search) | df["short_code"].fillna("").str.lower().str.contains(search)]

# session state for absolute counts
if "counts" not in st.session_state:
    st.session_state["counts"] = {}
counts = st.session_state["counts"]

# -------------------- Items grid --------------------
for _, row in df.iterrows():
    rid = row.id
    display_name = (row.short_code or row.name or "Unnamed Ingredient").strip()
    current = float(row.on_hand)
    if rid not in counts:
        counts[rid] = current

    with st.container():
        c1, c2, c3 = st.columns([3, 1.5, 1])

        with c1:
            st.markdown(f"<div class='item-title'>{display_name}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='item-sub'>Vendor: {row.vendor or '-'} • Current: {current:.2f}</div>",
                unsafe_allow_html=True,
            )

        with c2:
            val = st.number_input(
                "On Hand",
                key=f"{area}_{rid}",
                value=float(counts[rid]),
                step=0.5,
                label_visibility="collapsed",
            )
            counts[rid] = float(val)

        with c3:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button("💾 Save", key=f"save_{rid}"):
                try:
                    save_absolute_count(conn, rid, counts[rid])
                    st.success(f"{display_name} updated!")
                except Exception as e:
                    st.error("Save failed.")
                    st.exception(e)

    st.markdown("---")
