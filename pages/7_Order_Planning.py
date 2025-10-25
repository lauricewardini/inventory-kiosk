import streamlit as st
import pandas as pd
from lib.inv_helpers import get_conn

st.set_page_config(page_title="Order Planning", layout="wide")
st.title("🧾 Order Planning")

conn = get_conn()

df = pd.read_sql("""
  with onhand as (
    select ingredient_id, sum(case when type='in' then qty else -qty end) as on_hand
    from inventory_txns group by ingredient_id
  )
  select i.id as ingredient_id, i.name, i.unit, i.vendor, i.area,
         coalesce(i.weekly_usage,0) as weekly_usage,
         coalesce(o.on_hand,0) as on_hand,
         coalesce(i.par,0) as par_override,
         coalesce(i.cost_per_unit,0) as cost_per_unit
  from ingredients i
  left join onhand o on o.ingredient_id = i.id
  order by i.vendor nulls last, i.name;
""", conn)

df["daily_usage"] = df["weekly_usage"] / 7.0
# If par_override > 0, use it; else formula (daily_usage * 11)
df["par_calc"] = (df["daily_usage"] * 11).round(4)
df["par"] = df.apply(lambda r: r["par_override"] if r["par_override"] and r["par_override"] > 0 else r["par_calc"], axis=1)
df["to_order"] = (df["par"] - df["on_hand"]).clip(lower=0)
df["line_total"] = (df["to_order"] * df["cost_per_unit"]).round(2)

vendors = ["All"] + sorted(list(set(df["vendor"].dropna())))
vendor = st.selectbox("Vendor", vendors, index=0)

view = df if vendor == "All" else df[df["vendor"] == vendor]
st.dataframe(
    view[["vendor","name","unit","area","daily_usage","par","on_hand","to_order","cost_per_unit","line_total"]],
    use_container_width=True, hide_index=True
)

tot = float(view["line_total"].sum())
st.metric("Estimated Order Cost", f"${tot:,.2f}")

csv = view[["vendor","name","unit","area","to_order","cost_per_unit","line_total"]].to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download CSV for Vendor", csv, file_name=f"order_{vendor.lower() if vendor!='All' else 'all'}.csv", mime="text/csv")

