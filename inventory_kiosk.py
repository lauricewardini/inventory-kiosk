# inventory_kiosk.py
import pandas as pd
import streamlit as st

# If your helpers live under /lib
from lib.lib_db import get_conn
from lib.lib_kiosk import render_kiosk

st.set_page_config(page_title="Donut Land Inventory Dashboard", layout="wide")
st.title("🍩 Donut Land Inventory Dashboard")

# ---- Connect
try:
    conn = get_conn()
except Exception as e:
    st.error("❌ Could not connect to Supabase. Check the DATABASE_URL in Streamlit > Settings > Secrets.")
    st.exception(e)
    st.stop()

# ---- Always show something first: All Items (no filters)
st.subheader("All Items (live from Supabase)")
all_items = pd.read_sql("""
  with onhand as (
    select ingredient_id, sum(case when type='in' then qty else -qty end) as on_hand
    from inventory_txns group by ingredient_id
  )
  select i.id, i.name, i.unit, i.vendor, i.area,
         coalesce(o.on_hand,0) as on_hand,
         i.weekly_usage
  from ingredients i
  left join onhand o on o.ingredient_id = i.id
  order by i.name;
""", conn)

if all_items.empty:
    st.info("No ingredients found yet. Add rows in Supabase → Table Editor → **ingredients**. "
            "Fill in **name, unit, area, weekly_usage** and add at least one row in **inventory_txns**.")
else:
    st.dataframe(all_items, use_container_width=True, hide_index=True)

st.divider()

# ---- Area picker (auto-populated from your data)
areas = sorted([a for a in all_items["area"].dropna().unique().tolist()]) if not all_items.empty else []
st.subheader("Count by Area")
if areas:
    selected = st.selectbox("Choose an area", areas, index=0)
    # Render the kiosk for the chosen area (tap-to-count UI)
    render_kiosk(conn, area=selected, title=f"{selected} Inventory")
else:
    st.info("No areas found yet. Make sure your `ingredients.area` values are set (e.g., Kitchen, Utility Room, Baking Area, BOH Rack 1, Bagel Area, BOH Fridge Rack).")
