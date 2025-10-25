import os
import pandas as pd
import psycopg2
import streamlit as st

def get_conn():
    db = os.environ.get("DATABASE_URL") or st.secrets.get("DATABASE_URL")
    if not db:
        st.error("DATABASE_URL not set. Add it to .streamlit/secrets.toml or Streamlit Cloud Secrets.")
        st.stop()
    return psycopg2.connect(db)

def load_area_df(conn, area_name: str) -> pd.DataFrame:
    q = """
    with onhand as (
      select ingredient_id, sum(case when type='in' then qty else -qty end) as on_hand
      from inventory_txns group by ingredient_id
    )
    select i.id as ingredient_id, i.name, i.unit, i.area, i.vendor,
           coalesce(o.on_hand,0) as on_hand
    from ingredients i
    left join onhand o on o.ingredient_id = i.id
    where i.area = %s
    order by i.name;
    """
    return pd.read_sql(q, conn, params=(area_name,))

def save_count_adjustments(conn, base_map, new_map):
    diffs = []
    for rid, new_val in new_map.items():
        base_val = float(base_map.get(rid, 0.0))
        if abs(new_val - base_val) > 1e-9:
            diffs.append((rid, new_val))
    if not diffs:
        return 0

    with conn, conn.cursor() as cur:
        for rid, new_val in diffs:
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
    return len(diffs)

def area_counter_ui(area_name: str):
    import math
    from datetime import datetime

    st.title(f"📦 {area_name} — Inventory Count")

    conn = get_conn()
    df = load_area_df(conn, area_name)

    if df.empty:
        st.info(f"No items found for area '{area_name}'. Add items in Settings.")
        return

    # Search and session state
    search = st.text_input("Search", placeholder=f"Search {area_name}…").strip().lower()
    filtered = df[df["name"].str.lower().str.contains(search)] if search else df

    if "counts" not in st.session_state:
        st.session_state["counts"] = {}
    counts = st.session_state["counts"]
    for _, row in df.iterrows():
        counts.setdefault(row.ingredient_id, float(row.on_hand))

    # Sidebar controls
    default_step = st.sidebar.number_input("Default step", 0.25, 100.0, value=1.0, step=0.25)
    quick_steps = st.sidebar.multiselect("Quick add buttons", [1,5,10,25,50], [1,5,10])

    # KPIs
    c1, c2, c3 = st.columns(3)
    with c1: st.metric("Items", len(filtered))
    base_map = {r.ingredient_id: float(r.on_hand) for _, r in df.iterrows()}
    adj_count = sum(1 for rid,v in counts.items() if abs(v - float(base_map.get(rid,0.0))) > 1e-9)
    with c2: st.metric("Adjusted this session", adj_count)
    with c3: st.metric("Time", datetime.now().strftime("%-I:%M %p"))

    # Render cards in a grid
    per_row = 3
    rows = math.ceil(len(filtered)/per_row) if len(filtered) else 0
    idx = 0
    for _ in range(rows):
        cols = st.columns(per_row)
        for col in cols:
            if idx >= len(filtered): break
            row = filtered.iloc[idx]
            rid = row.ingredient_id
            with col:
                st.markdown("""
                    <style>
                    .card {border:1px solid #E3E6EA; border-radius:12px; padding:16px; height:100%; background:#fff;}
                    .count {font-size: 26px; font-weight:700; margin: 6px 0 0 0;}
                    .name {font-weight:600; font-size:16px; margin:0;}
                    .unit {color:#667085; font-size:13px; margin:0;}
                    </style>
                """, unsafe_allow_html=True)
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"<p class='name'>{row.name}</p>", unsafe_allow_html=True)
                st.markdown(f"<p class='unit'>Unit: {row.unit} • Vendor: {row.vendor or '—'}</p>", unsafe_allow_html=True)
                st.markdown(f"<p class='unit'>Current: {row.on_hand:.2f}</p>", unsafe_allow_html=True)
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
                    if st.button("✔", key=f"ok_{rid}"): counts[rid] = float(val)
                st.markdown("</div>", unsafe_allow_html=True)
            idx += 1

    st.session_state["counts"] = counts

    st.markdown("---")
    left, right = st.columns([3,2])
    with left:
        changes = []
        for rid, new_val in counts.items():
            base_val = float(base_map.get(rid,0.0))
            if abs(new_val - base_val) > 1e-9:
                item = df[df.ingredient_id == rid].iloc[0]
                changes.append({"Ingredient": item["name"], "New On Hand": round(new_val,2), "Delta": round(new_val - base_val,2)})
        if changes:
            st.write("Review changes:")
            st.dataframe(pd.DataFrame(changes), use_container_width=True, hide_index=True)
        else:
            st.info("No changes yet.")

    with right:
        colA, colB = st.columns(2)
        if colA.button("💾 Save Counts", use_container_width=True):
            n = save_count_adjustments(conn, base_map, counts)
            st.success(f"Saved {n} adjustments.")
        if colB.button("↩️ Reset Session", use_container_width=True):
            for _, r in df.iterrows():
                counts[r.ingredient_id] = float(r.on_hand)
            st.rerun()

