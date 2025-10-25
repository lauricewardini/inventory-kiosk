import streamlit as st
from lib.inv_helpers import get_conn
import pandas as pd

st.set_page_config(page_title="Donut Land • Inventory", page_icon="🍩", layout="wide")
st.title("🍩 Donut Land — Inventory Dashboard")

st.write("Pick an area from the sidebar pages to start counting. Common areas are pre-created.")

conn = get_conn()
df = pd.read_sql("select area, count(*) as items from ingredients group by area order by area;", conn)

c1, c2 = st.columns(2)
with c1:
    st.subheader("Areas & Item Counts")
    st.dataframe(df, use_container_width=True, hide_index=True)
with c2:
    st.subheader("Quick Links")
    st.markdown("- **Order Planning** → see page: *Order Planning* in the sidebar")
    st.markdown("- **Settings** → edit Vendors, Areas, Weekly Usage")

st.info("TIP: On iPad, add this app to Home Screen (Safari → Share → Add to Home Screen).")
