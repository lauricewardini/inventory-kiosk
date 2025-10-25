import streamlit as st
import pandas as pd
from lib.lib_db import get_conn  # we'll create this next

def render_kiosk(conn=None, area=None, title=None):
    st.set_page_config(page_title=title or "Inventory Kiosk", layout="wide")
    st.title(f"📦 {title or 'Inventory'}")

    if conn is None:
        conn = get_conn()

    query = """
    with onhand as (
        select ingredient_id, sum(case when type='in' then qty else -qty end) as on_hand
        from inventory_txns
        group by ingredient_id
    )
    select i.id, i.name, i.unit, i.vendor, i.area,
           coalesce(o.on_hand,0) as on_hand,
           i.weekly_usage
    from ingredients i
    left join onhand o on o.ingredient_id = i.id
    where (%(area)s is null or i.area = %(area)s)
    order by i.name;
    """

    df = pd.read_sql(query, conn, params={"area": area})

    if df.empty:
        st.info("No items found for this area. Add ingredients in Supabase and set their Area to match this page.")
        return

    for _, row in df.iterrows():
        col1, col2, col3 = st.columns([3, 1, 2])
        col1.markdown(f"**{row['name']}** ({row['unit']})")
        col2.markdown(f"On hand: {row['on_hand']}")
        delta = col3.number_input(
            f"Adjust {row['name']}",
            min_value=-1000,
            max_value=1000,
            value=0,
            key=row["id"],
            step=1
        )

    st.button("💾 Save Counts", use_container_width=True)
