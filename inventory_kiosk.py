import streamlit as st
from lib.lib_db import get_conn
from lib.lib_kiosk import render_kiosk

# --- PAGE CONFIG ---
st.set_page_config(page_title="Donut Land Inventory Dashboard", layout="wide")

# --- HEADER ---
st.title("🍩 Donut Land Inventory Dashboard")

st.markdown("""
Welcome to the Inventory Kiosk!  
Use the sidebar to navigate between different areas (Kitchen, Bagel Area, BOH, etc.)  
Each page shows items in that area, lets you adjust counts, and log waste or usage.
""")

# --- CONNECT TO DATABASE ---
try:
    conn = get_conn()
    st.success("✅ Connected to Supabase database.")
except Exception as e:
    st.error("❌ Could not connect to Supabase database. Check your DATABASE_URL secret.")
    st.exception(e)
    st.stop()

# --- MAIN DASHBOARD CONTENT ---
st.markdown("### Choose an area to manage inventory")

# Example of quick-access buttons (you can edit or add more)
col1, col2, col3 = st.columns(3)

if col1.button("🥣 Kitchen"):
    render_kiosk(conn, area="Kitchen", title="Kitchen Inventory")

if col2.button("🥯 Bagel Area"):
    render_kiosk(conn, area="Bagel Area", title="Bagel Area Inventory")

if col3.button("🧈 BOH Fridge Rack"):
    render_kiosk(conn, area="BOH Fridge Rack", title="BOH Fridge Rack Inventory")

st.divider()
st.markdown("""
If you don’t see items yet:
1. Make sure your **ingredients** table in Supabase has rows.
2. Each ingredient must have an **area** value that matches exactly (e.g., “Kitchen”).
3. Add a few rows to **inventory_txns** (type = `in`, qty = starting stock).
""")
