# inventory_kiosk.py

import os
from typing import Optional, List, Tuple

import streamlit as st
import pandas as pd
import psycopg2
import psycopg2.extras

# -------------------------
# Page / Theme
# -------------------------
st.set_page_config(page_title="Donut Land – Inventory", layout="wide")
st.markdown("""
<style>
.metric-card{background:#fffafc;border:1px solid #f1e1eb;border-radius:12px;padding:16px;box-shadow:0 1px 2px rgba(0,0,0,.05)}
.item-title{font-size:18px;font-weight:700;color:#c94d94;margin-bottom:4px}
.subtle{color:#6c757d;font-size:13px}
.center-input input{text-align:center !important;font-weight:600 !important}
[data-testid="stTable"] td, [data-testid="stDataFrame"] td{font-size:13px}
</style>
""", unsafe_allow_html=True)

# -------------------------
# DB Helpers
# -------------------------
def get_conn():
    """
    Connect using, in order of preference:
    1) st.secrets["DATABASE_URL"] or env DATABASE_URL (full DSN)
    2) st.secrets["pg"] dict or PG* envs (host/port/db/user/pwd + optional sslmode)
    """
    dsn = (st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL"))
    if dsn:
        return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    cfg = st.secrets.get("pg", {})
    host = cfg.get("host") or os.environ.get("PGHOST", "localhost")
    port = int(cfg.get("port") or os.environ.get("PGPORT", "5432"))
    db   = cfg.get("dbname") or os.environ.get("PGDATABASE", "postgres")
    user = cfg.get("user") or os.environ.get("PGUSER", "postgres")
    pwd  = cfg.get("password") or os.environ.get("PGPASSWORD", "")
    sslmode = cfg.get("sslmode") or os.environ.get("PGSSLMODE", "")

    kwargs = dict(host=host, port=port, dbname=db, user=user, password=pwd,
                  cursor_factory=psycopg2.extras.RealDictCursor)
    if sslmode:
        kwargs["sslmode"] = sslmode  # e.g., "require" on Supabase/Neon
    return psycopg2.connect(**kwargs)

def db_available() -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("select 1;")
        return True
    except Exception as e:
        st.session_state["_db_err"] = str(e)
        return False

def run_query(sql: str, params: Optional[Tuple]=None) -> List[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if cur.description:
                return cur.fetchall()
            return []

def run_execute(sql: str, params: Tuple):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()

def insert_txn(ingredient_id:str, ttype:str, qty:float, unit_cost:Optional[float], source:str, ref_id:Optional[str]=None):
    run_execute("""
        insert into inventory_txns (ingredient_id, type, qty, unit_cost, source, ref_id)
        values (%s, %s, %s, %s, %s, %s)
    """, (ingredient_id, ttype, qty, unit_cost, source, ref_id))

# -------------------------
# Data Access
# -------------------------
@st.cache_data
def distinct_vendor_list() -> List[str]:
    rows = run_query("""
        select distinct vendor from ingredients
        where vendor is not null and vendor <> '' order by vendor;
    """)
    return [r["vendor"] for r in rows]

@st.cache_data
def distinct_area_list() -> List[str]:
    rows = run_query("""
        select distinct area from ingredients
        where area is not null and area <> '' order by area;
    """)
    return [r["area"] for r in rows]

def ingredient_rows_by_area(area: str, search: str = "") -> pd.DataFrame:
    sql = """
      select id, name, unit, vendor, area
      from ingredients
      where area = %s
    """
    params = [area]
    if search:
        sql += " and (name ilike %s or coalesce(vendor,'') ilike %s or coalesce(short_code,'') ilike %s)"
        like = f"%{search}%"
        params.extend([like, like, like])
    sql += " order by name"
    return pd.DataFrame(run_query(sql, tuple(params)))

def onhand_df() -> pd.DataFrame:
    # Prefer view; fallback inline if not present:
    try:
        rows = run_query("select ingredient_id, name, on_hand from v_onhand;")
    except Exception:
        rows = run_query("""
            select i.id as ingredient_id, i.name,
                   coalesce(sum(case when t.type='in' then t.qty else -t.qty end),0) as on_hand
            from ingredients i
            left join inventory_txns t on t.ingredient_id = i.id
            group by i.id, i.name
        """)
    return pd.DataFrame(rows)

def order_planning_df(vendor: Optional[str] = None) -> pd.DataFrame:
    sql = """
        select
          i.id as ingredient_id,
          i.name,
          i.unit,
          i.vendor,
          i.area,
          i.weekly_usage,
          (i.weekly_usage/7.0) as daily_usage,
          coalesce(i.par, (i.weekly_usage/7.0)*11.0) as par_level,
          coalesce(oh.on_hand, 0) as current_stock,
          greatest(0, coalesce(i.par, (i.weekly_usage/7.0)*11.0) - coalesce(oh.on_hand,0)) as to_order
        from ingredients i
        left join (
            select ingredient_id,
                   coalesce(sum(case when type='in' then qty else -qty end),0) as on_hand
            from inventory_txns
            group by ingredient_id
        ) oh on oh.ingredient_id = i.id
        where 1=1
    """
    params = []
    if vendor:
        sql += " and i.vendor = %s"
        params.append(vendor)
    sql += " order by coalesce(i.vendor,'zzz'), i.name"
    rows = run_query(sql, tuple(params))
    return pd.DataFrame(rows)

def costs_df() -> pd.DataFrame:
    return pd.DataFrame(run_query("select id, cost_per_unit from ingredients;"))

def weekly_usage_table() -> pd.DataFrame:
    return pd.DataFrame(run_query("""
        select id, name, vendor, area, unit, weekly_usage
        from ingredients
        order by coalesce(area,'zzz'), name
    """))

def save_weekly_usage(updates: pd.DataFrame):
    for _, r in updates.iterrows():
        run_execute(
            "update ingredients set weekly_usage=%s where id=%s",
            (float(r["weekly_usage"] or 0.0), r["id"])
        )

# -------------------------
# Guard: DB must be reachable
# -------------------------
if not db_available():
    st.sidebar.warning("Database not connected")
    st.error(
        "I can’t reach the database.\n\n"
        "• On Streamlit Cloud, set **Secrets** to either:\n"
        "  - `DATABASE_URL = postgresql://user:pass@host:port/db?sslmode=require`\n"
        "  - or `[pg]` keys (host/port/db/user/password, sslmode=require)\n"
        "• For Supabase (direct): host=`db.<ref>.supabase.co`, port=`5432`, sslmode=`require`.\n"
        "• For Supabase (pooler): host=`aws-1-us-east-1.pooler.supabase.com`, port=`6543`, "
        "  username format `<dbuser>.<project_ref>`, sslmode=`require`."
    )
    st.code(st.session_state.get("_db_err",""), language="text")
    st.stop()

# -------------------------
# Sidebar Navigation
# -------------------------
st.sidebar.header("Donut Land Inventory")

# Preferred areas first (your order), then auto-add any others found in DB
preferred_areas = ["Kitchen", "Utility Room", "Baking Area", "BOH Rack 1", "Bagel Area", "BOH FridgeRack"]
db_areas = distinct_area_list()
ordered_areas = [a for a in preferred_areas if a in db_areas] + [a for a in db_areas if a not in preferred_areas]

nav_items = [f"📍 {a}" for a in ordered_areas] + ["🧾 Order Planning", "⚙️ Settings"]
page = st.sidebar.radio("Go to", nav_items, index=0)

# -------------------------
# Pages
# -------------------------
def show_area_page(area_name: str):
    st.subheader(f"Physical Count – {area_name}")
    st.caption("Enter what you **see** on the floor. We’ll post the delta as an *adjustment* transaction.")
    left, right = st.columns([2,1])

    with left:
        search = st.text_input("Search (name, vendor, short code)", key=f"search_{area_name}")
        items = ingredient_rows_by_area(area_name, search)
        if items.empty:
            st.info("No items found in this area.")
            return

        oh = onhand_df().rename(columns={"ingredient_id":"id"})
        df = items.merge(oh[["id","on_hand"]], on="id", how="left").fillna({"on_hand":0.0})
        df = df[["id","name","vendor","unit","on_hand"]].copy()
        df["count_now"] = 0.0

        # Editable grid (keep ID disabled instead of hidden; Streamlit version compatibility)
        st.data_editor(
            df,
            key=f"editor_{area_name}",
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("ID", disabled=True),
                "name": st.column_config.TextColumn("Item", disabled=True),
                "vendor": st.column_config.TextColumn("Vendor", disabled=True),
                "unit": st.column_config.TextColumn("Unit", disabled=True),
                "on_hand": st.column_config.NumberColumn("On Hand (system)", format="%.4f", disabled=True),
                "count_now": st.column_config.NumberColumn("Physical Count", format="%.4f"),
            },
            num_rows="fixed"
        )

        if st.button("Post Adjustments", type="primary", key=f"post_{area_name}"):
            edited = st.session_state.get(f"editor_{area_name}")
            posted = 0
            if isinstance(edited, pd.DataFrame):
                for _, r in edited.iterrows():
                    target = float(r.get("count_now") or 0.0)
                    current = float(r.get("on_hand") or 0.0)
                    delta = round(target - current, 4)
                    if abs(delta) < 1e-9:
                        continue
                    ttype = "in" if delta > 0 else "out"
                    insert_txn(
                        ingredient_id=r["id"],
                        ttype=ttype,
                        qty=abs(delta),
                        unit_cost=None,
                        source="adjustment",
                        ref_id=None
                    )
                    posted += 1
            st.success(f"Posted {posted} adjustment(s).")
            st.rerun()

    with right:
        st.subheader("Quick Add Usage/Waste")
        choices = items.sort_values("name") if 'items' in locals() else pd.DataFrame()
        if not choices.empty:
            sel = st.selectbox("Item", options=choices["name"].tolist(), key=f"quick_sel_{area_name}")
            row = choices.loc[choices["name"] == sel].iloc[0]
            qty = st.number_input("Qty (out)", min_value=0.0, step=0.1, key=f"quick_qty_{area_name}")
            source = st.selectbox("Reason", ["production","waste"], index=0, key=f"quick_src_{area_name}")
            if st.button("Save Quick Out", key=f"quick_btn_{area_name}", disabled=qty<=0):
                insert_txn(row["id"], "out", qty, None, source)
                st.success("Saved.")
                st.rerun()

def show_order_planning():
    st.subheader("Order Planning (Par = daily × 11)")
    v_opts = ["(All)"] + distinct_vendor_list()
    vendor = st.selectbox("Vendor", v_opts, index=0)
    vendor = None if vendor == "(All)" else vendor

    plan = order_planning_df(vendor)
    if plan.empty:
        st.info("No rows.")
        return

    c = costs_df()
    # ✅ fixed merge syntax
    plan = plan.merge(c, left_on="ingredient_id", right_on="id", how="left")
    plan["est_cost"] = (plan["to_order"] * plan["cost_per_unit"]).fillna(0.0)

    st.dataframe(
        plan[["vendor","name","unit","area","weekly_usage","daily_usage",
              "par_level","current_stock","to_order","cost_per_unit","est_cost"]]
        .sort_values(["vendor","name"]),
        use_container_width=True, hide_index=True
    )

    totals = plan.groupby("vendor", dropna=False)["est_cost"].sum().reset_index().rename(columns={"est_cost":"Est. PO Cost"})
    st.markdown("### Estimated PO Cost by Vendor")
    st.dataframe(totals, use_container_width=True, hide_index=True)

def show_settings():
    st.subheader("Settings")
    (tab1,) = st.tabs(["Seasonal Weekly Usage"])
    with tab1:
        st.caption("Adjust weekly usage to reflect seasonality. Par is auto-recalculated (daily × 11).")
        data = weekly_usage_table()
        if data.empty:
            st.info("No ingredients found.")
            return
        edited = st.data_editor(
            data,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("ID", disabled=True),
                "name": st.column_config.TextColumn("Ingredient", disabled=True),
                "vendor": st.column_config.TextColumn("Vendor", disabled=True),
                "area": st.column_config.TextColumn("Area", disabled=True),
                "unit": st.column_config.TextColumn("Unit", disabled=True),
                "weekly_usage": st.column_config.NumberColumn("Weekly Usage", format="%.4f"),
            },
            num_rows="fixed"
        )
        if st.button("Save Weekly Usage", type="primary"):
            save_weekly_usage(edited[["id","weekly_usage"]])
            st.success("Weekly usage saved.")
            st.cache_data.clear()  # refresh distinct lists/derived views

# -------------------------
# Router
# -------------------------
if page.startswith("📍 "):
    show_area_page(page.replace("📍 ",""))
elif page == "🧾 Order Planning":
    show_order_planning()
else:
    show_settings()
