"""Water main repair priority dashboard (Streamlit in Snowflake).

Owner: Aritha. Reads CURATED.PIPE_REPAIR_PRIORITY (survival model output,
Wayne and Sun) plus the tables built by 03_curated.sql and 04_risk_score.sql.
Tabs:
  1. Priority list     - which pipes to act on first, and why
  2. Pipe details      - one pipe: risk over time, drivers, break history
  3. How well it works - model vs real 2026 breaks, and the rule-based baseline
  4. Platform health   - credits used (Jibin's monitoring views)
"""
from decimal import Decimal

import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Water main repair priority", layout="wide")

session = get_active_session()
# Tag queries so app costs show up in MONITORING.V_CREDITS_BY_QUERY_TAG
session.sql("ALTER SESSION SET QUERY_TAG = 'streamlit'").collect()

DB = "LEAK_DB.CURATED"
BAND_ORDER = ["IMMEDIATE", "HIGH", "PLANNED", "MONITOR"]
FEATURE_NAMES = {
    "past_break_count": "Past breaks",
    "breaks_last_3y": "Breaks in last 3 years",
    "years_since_last_break": "Years since last break",
    "had_prior_break": "Has broken before",
    "age_years": "Age (years)",
    "material": "Material",
    "pipe_size": "Diameter (mm)",
    "length_m": "Length (m)",
    "pressure_zone": "Pressure zone",
}


@st.cache_data(ttl=600)
def run(query: str) -> pd.DataFrame:
    """Run a query and return a DataFrame with lower-case column names.

    Some tables were loaded from CSV with every column as text, so convert
    number-like and true/false text columns to proper types here.
    """
    df = session.sql(query).to_pandas()
    df.columns = [c.lower() for c in df.columns]
    for col in df.columns:
        # Leave columns that already have a proper type alone
        if (pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col])
                or pd.api.types.is_datetime64_any_dtype(df[col])):
            continue
        sample = df[col].dropna()
        if sample.empty:
            continue
        # Snowflake NUMBER columns can arrive as Python Decimal objects
        if isinstance(sample.iloc[0], Decimal):
            df[col] = df[col].astype(float)
            continue
        # Numbers stored as text -> numbers
        if pd.to_numeric(sample, errors="coerce").notna().all():
            df[col] = pd.to_numeric(df[col], errors="coerce")
            continue
        # "true"/"false" stored as text -> real booleans
        if set(sample.astype(str).str.strip().str.lower().unique()) <= {"true", "false"}:
            df[col] = df[col].map(lambda x: None if pd.isna(x) else str(x).strip().lower() == "true")
    return df


def describe_driver(feature, value, direction) -> str:
    """Turn a model driver into plain English, e.g. 'Past breaks: 12 (raises risk)'."""
    if pd.isna(feature):
        return ""
    name = FEATURE_NAMES.get(str(feature), str(feature))
    try:
        shown = f"{float(value):,.0f}"
    except (TypeError, ValueError):
        shown = str(value)
    return f"{name}: {shown} ({direction})"


scores = run(f"SELECT * FROM {DB}.PIPE_REPAIR_PRIORITY ORDER BY priority_rank")
for i in (1, 2, 3):
    scores[f"driver_{i}"] = [
        describe_driver(f, v, d)
        for f, v, d in zip(scores[f"driver_{i}_feature"], scores[f"driver_{i}_value"], scores[f"driver_{i}_direction"])
    ]
scores["risk_12m_pct"] = (scores["risk_probability_12m"] * 100).round(1)
scores["criticality_shown"] = [
    f"{c:.0f} (estimated)" if imputed else f"{c:.0f}"
    for c, imputed in zip(scores["criticality_used"], scores["criticality_was_imputed"])
]

# Real breaks since the scoring date: an honest out-of-sample check
as_of = str(scores["as_of_date"].iloc[0])[:10]
check = run(
    f"""
    WITH broke AS (
        SELECT DISTINCT TRY_TO_NUMBER(matched_asset_id) AS asset_id
        FROM {DB}.FACT_FAILURE
        WHERE reliable_event AND incident_date >= '{as_of}'::TIMESTAMP_NTZ
    )
    SELECT
        COUNT(b.asset_id) AS pipes_broken,
        COUNT_IF(b.asset_id IS NOT NULL AND p.priority_percentile >= 95) AS caught_top_5pct,
        COUNT_IF(b.asset_id IS NOT NULL AND p.priority_percentile >= 90) AS caught_top_10pct
    FROM {DB}.PIPE_REPAIR_PRIORITY AS p
    LEFT JOIN broke AS b
        ON p.asset_id = b.asset_id
    """
).iloc[0]
broken = int(check["pipes_broken"])
caught5 = int(check["caught_top_5pct"])

# ---------------------------------------------------------------- header
st.title("Water main repair priority")
st.caption(
    f"Scored as of {as_of} · survival model, likelihood weighted by criticality · "
    "City of Kitchener open data"
)

c1, c2, c3 = st.columns(3)
c1.metric("Pipes scored", f"{len(scores):,}")
c2.metric("IMMEDIATE + HIGH (top 5%)", f"{scores['priority_band'].isin(['IMMEDIATE', 'HIGH']).sum():,}")
c3.metric(
    f"{as_of[:4]} breaks so far in the top 5%",
    f"{caught5} of {broken}",
    help="Pipes that actually broke after the scoring date. Random 5% would catch about 5%.",
)

# ---------------------------------------------------------------- filters
st.sidebar.header("Filters")
bands = st.sidebar.multiselect("Priority band", BAND_ORDER, default=["IMMEDIATE", "HIGH"])
materials = st.sidebar.multiselect("Material", sorted(scores["material"].dropna().unique()))
zones = st.sidebar.multiselect("Pressure zone", sorted(scores["pressure_zone"].dropna().unique()))

view = scores[scores["priority_band"].isin(bands)] if bands else scores
if materials:
    view = view[view["material"].isin(materials)]
if zones:
    view = view[view["pressure_zone"].isin(zones)]

tab_list, tab_pipe, tab_eval, tab_platform = st.tabs(
    ["Priority list", "Pipe details", "How well it works"]
)

# ---------------------------------------------------------------- 1. priority list
with tab_list:
    st.subheader(f"{len(view):,} pipes match the filters")
    st.dataframe(
        view[[
            "priority_rank", "asset_id", "priority_band", "risk_12m_pct", "recommended_action",
            "driver_1", "driver_2", "driver_3", "material", "criticality_shown",
        ]].rename(columns={"risk_12m_pct": "break chance 12m (%)", "criticality_shown": "criticality"}).head(500),
        hide_index=True,
        use_container_width=True,
    )
    st.caption("Showing up to 500 rows. Criticality marked 'estimated' was missing in the source and filled in.")
    band_counts = scores["priority_band"].value_counts().reindex(BAND_ORDER).fillna(0)
    st.bar_chart(band_counts, height=220)

# ---------------------------------------------------------------- 2. pipe details
with tab_pipe:
    options = view["asset_id"].head(200).tolist()
    if not options:
        st.info("No pipes match the filters.")
    else:
        asset_id = int(st.selectbox("Pipe (top 200 of the current filter)", options))
        pipe = view[view["asset_id"] == asset_id].iloc[0]

        a, b, c, d = st.columns(4)
        a.metric("Rank", f"{int(pipe['priority_rank']):,}")
        b.metric("Band", pipe["priority_band"])
        c.metric("Break chance, 12 months", f"{pipe['risk_probability_12m']:.1%}")
        d.metric("Criticality", pipe["criticality_shown"])
        st.write(f"**Recommended action:** {pipe['recommended_action']}")

        left, right = st.columns(2)
        with left:
            st.write("**Chance of a break over time**")
            st.bar_chart(
                pd.Series(
                    [pipe["risk_probability_12m"], pipe["risk_probability_24m"], pipe["risk_probability_36m"]],
                    index=["12 months", "24 months", "36 months"],
                ),
                height=220,
            )
        with right:
            st.write("**Top drivers (positive = raises risk)**")
            st.bar_chart(
                pd.Series(
                    [pipe[f"driver_{i}_contribution"] for i in (1, 2, 3)],
                    index=[FEATURE_NAMES.get(str(pipe[f"driver_{i}_feature"]), str(pipe[f"driver_{i}_feature"])) for i in (1, 2, 3)],
                ),
                height=220,
            )

        # asset_id is an integer from our own table, so it is safe to put in the query
        history = run(
            f"SELECT incident_date, nature_of_break, apparent_cause, est_hours_for_repair "
            f"FROM {DB}.FACT_FAILURE WHERE reliable_event AND matched_asset_id = '{asset_id}' "
            f"ORDER BY incident_date DESC"
        )
        st.write(f"**Recorded breaks on this pipe: {len(history)}**")
        if not history.empty:
            st.dataframe(history, hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- 3. evaluation
with tab_eval:
    st.subheader(f"Did the {as_of} ranking find the pipes that broke?")
    e1, e2 = st.columns(2)
    e1.metric("Broken pipes in the top 5%", f"{caught5} of {broken}",
              f"{caught5 / max(broken, 1):.0%} caught (random: 5%)")
    e2.metric("Broken pipes in the top 10%", f"{int(check['caught_top_10pct'])} of {broken}",
              f"{int(check['caught_top_10pct']) / max(broken, 1):.0%} caught (random: 10%)")
    st.caption("Only breaks recorded after the scoring date count. The year is not over, so this will change.")

    st.subheader("Baseline for comparison: simple rule-based score")
    st.write(
        "A transparent points score (past breaks, material, age, length, diameter), "
        "backtested on every year from 2015 to 2025 using only data from before each 1 January."
    )
    try:
        baseline = run(f"SELECT * FROM {DB}.RISK_SCORE_EVALUATION ORDER BY snapshot_year")
        st.line_chart(baseline.set_index("snapshot_year")[["recall_top_5pct", "recall_top_10pct"]], height=240)
        st.dataframe(baseline, hide_index=True, use_container_width=True)
    except Exception as exc:  # baseline table is optional
        st.info(f"Baseline table not available: {exc}")

# ---------------------------------------------------------------- 4. platform health
# #with tab_platform:
#     st.subheader("Cost and usage")
#     try:
#         summary = run("SELECT * FROM LEAK_DB.MONITORING.V_CREDIT_SUMMARY")
#         by_tag = run(
#             "SELECT query_tag, SUM(queries) AS queries, SUM(credits_attributed) AS credits "
#             "FROM LEAK_DB.MONITORING.V_CREDITS_BY_QUERY_TAG GROUP BY query_tag ORDER BY credits DESC"
#         )
#         used = float(summary["credits_used_30d"].iloc[0] or 0)
#         st.metric("Credits used (of 40 budget)", f"{used:.2f}", help="Usage data can lag by up to 3 hours.")
#         st.progress(min(used / 40, 1.0))
#         st.write("**Credits by workload (query tag)**")
#         st.dataframe(by_tag, hide_index=True, use_container_width=True)
#     except Exception as exc:  # monitoring views are optional for the demo
#         st.info(f"Monitoring views not available: {exc}")