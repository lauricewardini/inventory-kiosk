import os
from math import ceil
from datetime import datetime
import pandas as pd
import streamlit as st
import psycopg2

st.set_page_config(page_title="Donut Land Inventory Dashboard", layout="wide")
st.title("🍩 Donut Land Inventory Dashboard")

# ---------- DB connection (uses Streamlit Secrets or env) ----------
def get_conn():
    db_url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        st.error("DATABASE_URL secret is missing. Set it in Streamlit Cloud → App → ⋮ → Settings → Secrets.")
        st.stop()
    if "sslmode=" not in db_url:
        db_url = f"{db_url}?sslmode=require"
    return psycopg2.connect(db_url)

try:
    conn = get_conn()
    st.success("✅ Connected to Supabase.")
except Exception as e:
    st.error("❌ Could not connect to Supabase. Check DATABASE_URL in Secrets.")
    st.exception(e)
    st.stop()

# ---------- helpers ----------
def load_all_items(connection):
    q = """
      with onhand as (
        select ingredient_id, sum(case when type='in' then qty else -qty end) as on_hand
        from inventory_txns group by ingredient_id
      )
      select i.id, i.name, i.unit, i.vendor, i.area,
             coalesce(o.on_hand,0) as on_hand,
             coalesce(i.weekly_usage,0) as weekly_usage
      from ingredients i
      left join onhand o on o.ingredient_id = i.id
      order by i.name;
    """
    return pd.read_sql(q, connection)

def write_adjustments(connection, diffs, base_map):
    with connection, connection.cursor() as cur:
        for rid, new_value in diffs:
            # insert the delta needed to reach the absolute number user entered
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
            """, (rid, rid, new_value, new_value, new_value))

# ---------- Always show something first ----------
st.subheader("All Items (live)")
all_items = load_all_items(conn)

if all_items.empty:
    st.info(
        "No ingredients yet. In Supabase → **Table Editor**, add rows to **ingredients** "
        "(name, unit, vendor, area, weekly_usage). Then add at least one row per item to "
        "**inventory_txns** with `type = in`, `qty = starting stock`."
    )
else:
    st.dataframe(all_items, use_container_width=True, hide_index=True)

st.divider()

# ---------- Area picker ----------
areas = sorted([a for a in all_items["area"].dropna().unique().tolist()]) if not all_items.empty else []
st.subheader("Count by Area")
if not areas:
    st.info("No `area` values found. Ensure `ingredients.area` has values like 'Kitchen', 'Baking Area', etc.")
    st.stop()

selected = st.selectbox("Choose an area", areas, index=0)

# Filter to area
df = all_items[all_items["area"] == selected].copy()
if df.empty:
    st.info(f"No items found for area **{selected}**. Edit the `area` values in Supabase to match exactly.")
    st.stop()

# ---------- Tap-to-count kiosk (minimal) ----------
st.markdown("### Inventory Kiosk")
st.caption("Adjust the absolute **On Hand** amount for each item, then Save Counts.")

# session state of absolute counts per item in this area
ss_key = f"counts_{selected}"
if ss_key not in st.session_state:
    st.session_state[ss_key] = {row.id: float(row.on_hand) for _, row in df.iterrows()}
counts = st.session_state[ss_key]

# controls
left, right = st.columns([2,1])
with right:
    step = st.number_input("Default step", min_value=0.25, max_value=100.0, value=1.0, step=0.25)
with left:
    search = st.text_input("Search items", placeholder="Start typing...").strip().lower()
if search:
    df = df[df["name"].str.lower().str.contains(search)]

# grid of inputs
per_row = 2
rows = ceil(len(df)/per_row) if len(df) else 0
idx = 0
for _ in range(rows):
    cols = st.columns(per_row)
    for col in cols:
        if idx >= len(df): break
        row = df.iloc[idx]
        rid = row.id
        with col:
            st.markdown(f"**{row['name']}** ({row['unit']})  \nVendor: {row['vendor'] or '-'}")
            c1, c2, c3 = st.columns([2,1,1])
            with c1:
                val = st.number_input(
                    f"On hand — {row['name']}",
                    key=f"{selected}_set_{rid}",
                    value=float(counts.get(rid, 0.0)),
                    step=step,
                    label_visibility="collapsed"
                )
            with c2:
                if st.button("−", key=f"{selected}_minus_{rid}"):
                    val = max(0.0, float(counts.get(rid, 0.0)) - step)
            with c3:
                if st.button("+", key=f"{selected}_plus_{rid}"):
                    val = float(counts.get(rid, 0.0)) + step
            counts[rid] = float(val)
        idx += 1

st.session_state[ss_key] = counts

# review & save
st.markdown("---")
base_map = {row.id: float(row.on_hand) for _, row in df.iterrows()}
changes = [(rid, counts[rid]) for rid in counts.keys()
           if abs(counts[rid] - base_map.get(rid, 0.0)) > 1e-9]

colA, colB = st.columns([3,2])
with colA:
    if changes:
        review = pd.DataFrame([{
            "Item": df[df.id==rid].iloc[0]["name"],
            "New On Hand": round(new,2),
            "Previous": round(base_map.get(rid,0.0),2),
            "Delta": round(new - base_map.get(rid,0.0),2),
        } for rid, new in changes])
        st.write("Review changes:")
        st.dataframe(review, use_container_width=True, hide_index=True)
    else:
        st.info("No changes yet.")

with colB:
    if st.button("💾 Save Counts", use_container_width=True, disabled=not changes):
        try:
            write_adjustments(conn, changes, base_map)
            st.success("Counts saved. Refresh the page to see updated on-hand totals.")
        except Exception as e:
            st.error("Error saving counts.")
            st.exception(e)

st.caption(f"Showing area: **{selected}** • {datetime.now():%b %d, %I:%M %p}")
