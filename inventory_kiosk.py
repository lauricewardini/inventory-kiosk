import os
from math import ceil
from datetime import datetime
import pandas as pd
import streamlit as st
import psycopg2

# ---------- PAGE CONFIG ----------
st.set_page_config(page_title="Inventory Kiosk", page_icon="📦", layout="wide")

# ---------- CUSTOM STYLES ----------
st.markdown("""
    <style>
    .kpi {font-size: 28px; font-weight: 600; margin-bottom: 0;}
    .sub {color:#667085; font-size: 13px;}
    div[data-testid="stMetricValue"] {font-size: 28px;}
    button[kind="primary"] {font-size: 18px; padding: 12px 16px;}
    .card {border:1px solid #E3E6EA; border-radius:12px; padding:16px; height:100%; background:#fff;}
    .count {font-size: 26px; font-weight:700; margin: 6px 0 0 0;}
    .name {font-weight:600; font-size:16px; margin:0;}
    .unit {color:#667085; font-size:13px; margin:0;}
    .btnrow button {margin-right:6px; margin-top:6px;}
    </style>
""", unsafe_allow_html=True)

st.title("📦 Inventory Count (Kiosk)")

# ---------- DATABASE CONNECTION ----------
DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    st.error("DATABASE_URL not set")
    st.stop()

conn = psycopg2.connect(DB_URL)

# ---------- LOAD INGREDIENT DATA ----------
df = pd.read_sql("""
    with onhand as (
      select ingredient_id, sum(case when type='in' then qty else -qty end) as on_hand
      from inventory_txns group by ingredient_id
    )
    select i.id as ingredient_id, i.name, i.unit,
           coalesce(o.on_hand,0) as on_hand,
           coalesce(i.par,0) as safety_stock
    from ingredients i
    left join onhand o on o.ingredient_id = i.id
    order by i.name;
""", conn)

# ---------- SESSION STATE ----------
if "counts" not in st.session_state:
    st.session_state["counts"] = {row.ingredient_id: float(row.on_hand) for _, row in df.iterrows()}
counts = st.session_state["counts"]

# ---------- SIDEBAR SETTINGS ----------
default_step = st.sidebar.number_input("Default step", 0.25, 100.0, value=1.0, step=0.25)
quick_steps = st.sidebar.multiselect("Quick add buttons", [1,5,10,25,50], [1,5,10])
st.sidebar.caption("Tip: Use larger steps for bagged goods (e.g., +50 for 50lb flour).")

search = st.text_input("Search ingredients", placeholder="Type to filter…").strip().lower()
filtered = df[df["name"].str.lower().str.contains(search)] if search else df

# ---------- KPI HEADER ----------
c1, c2, c3 = st.columns(3)
with c1: st.metric("Items", len(filtered))
base_map = df.set_index('ingredient_id')["on_hand"].to_dict()
adj_count = sum(1 for rid,v in counts.items() if abs(v - float(base_map.get(rid,0.0))) > 1e-9)
with c2: st.metric("Adjusted this session", adj_count)
with c3: st.metric("Timestamp", datetime.now().strftime("%-I:%M %p"))

# ---------- GRID OF INGREDIENT CARDS ----------
per_row = 3
rows = ceil(len(filtered)/per_row) if len(filtered) else 0
idx = 0
for _ in range(rows):
    cols = st.columns(per_row)
    for col in cols:
        if idx >= len(filtered): break
        row = filtered.iloc[idx]
        rid = row.ingredient_id
        with col:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown(f"<p class='name'>{row.name}</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='unit'>Unit: {row.unit}</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='sub'>Current: {row.on_hand:.2f} • Safety: {row.safety_stock:.2f}</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='count'>On Hand: {counts.get(rid,0.0):.2f}</p>", unsafe_allow_html=True)

            bcols = st.columns(len(quick_steps)+3)
            if bcols[0].button("−", key=f"minus_{rid}"):
                counts[rid] = max(0.0, counts.get(rid,0.0) - default_step)
            if bcols[1].button("+", key=f"plus_{rid}"):
                counts[rid] = counts.get(rid,0.0) + default_step
            for i, step in enumerate(quick_steps):
                if bcols[i+2].button(f"+{step}", key=f"q{step}_{rid}"):
                    counts[rid] = counts.get(rid,0.0) + float(step)
            with bcols[-1]:
                val = st.number_input("Set", key=f"set_{rid}", value=float(counts.get(rid,0.0)), step=0.25, label_visibility="collapsed")
                if st.button("✔", key=f"ok_{rid}"):
                    counts[rid] = float(val)
            st.markdown("</div>", unsafe_allow_html=True)
        idx += 1

st.session_state["counts"] = counts

# ---------- SAVE BAR ----------
st.markdown("---")
left, right = st.columns([3,2])
with left:
    base = df.set_index("ingredient_id")["on_hand"].to_dict()
    diffs = [(rid, counts[rid] - base.get(rid, 0.0)) for rid in counts.keys() if abs(counts[rid] - base.get(rid,0.0)) > 1e-6]
    if diffs:
        st.write("Review changes:")
        review = pd.DataFrame([{
            "Ingredient": df[df.ingredient_id==rid].iloc[0]["name"],
            "New On Hand": round(counts[rid],2),
            "Delta": round(delta,2)
        } for rid, delta in diffs])
        st.dataframe(review, use_container_width=True, hide_index=True)
    else:
        st.info("No changes yet. Adjust counts above.")

def write_adjustments(diffs):
    with conn, conn.cursor() as cur:
        for rid, delta in diffs:
            new_val = base.get(rid,0.0) + delta
            cur.execute("""
                with current as (
                  select coalesce(sum(case when type='in' then qty else -qty end),0) as on_hand
                  from inventory_txns where ingredient_id = %s
                )
                insert into inventory_txns (ingredient_id, type, qty, source)
                select %s,
                       case when %s >= on_hand then 'in' else 'out' end,
                       abs(%s - on_hand),
                       'adjustment'
                from current
                where %s <> on_hand;
            """, (rid, rid, new_val, new_val, new_val))

with right:
    colA, colB = st.columns(2)
    if colA.button("💾 Save Counts", use_container_width=True):
        write_adjustments(diffs)
        st.success("Counts saved.")
    if colB.button("↩️ Reset Session", use_container_width=True):
        st.session_state["counts"] = {row.ingredient_id: float(row.on_hand) for _, row in df.iterrows()}
        st.rerun()

st.caption("Designed for iPad: big buttons, quick steps, and one-tap save.")
