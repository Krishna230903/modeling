import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
from datetime import datetime
import yfinance as yf

# =========================================================
# CONSTANTS
# =========================================================
MAX_KD_PRE_TAX = 0.20
MIN_KD_PRE_TAX = 0.01
DEFAULT_KD_PRE_TAX = 0.08
TERMINAL_VALUE_WARNING_THRESHOLD = 70.0
LEVERAGE_WARNING_THRESHOLD = 3.0
TG_BUFFER = 0.002

# =========================================================
# GLOBAL PLOTLY BLACK TEXT ENFORCEMENT (NEW)
# =========================================================
PLOTLY_BLACK = dict(
    font=dict(color="#000000"),
    title=dict(font=dict(color="#000000")),
    xaxis=dict(
        title_font=dict(color="#000000"),
        tickfont=dict(color="#000000")
    ),
    yaxis=dict(
        title_font=dict(color="#000000"),
        tickfont=dict(color="#000000")
    ),
    legend=dict(font=dict(color="#000000"))
)

# =========================================================
# STREAMLIT CONFIG
# =========================================================
st.set_page_config(
    page_title="Sentinel | Institutional Analytics",
    layout="wide",
    page_icon="🏛️",
    initial_sidebar_state="expanded"
)

# =========================================================
# CSS – UI POLISH (CARDS FIXED, BLACK TEXT)
# =========================================================
st.markdown("""
<style>
html, body, [class*="css"] {
    font-family: 'Inter', Helvetica, Arial, sans-serif;
    color: #000000 !important;
}
.stApp { background-color: #f4f6f8; }

/* SIDEBAR */
section[data-testid="stSidebar"] { background-color: #2c3e50; }
section[data-testid="stSidebar"] * { color: #ecf0f1 !important; }

/* KPI CARDS */
.metric-card {
    background-color: #ffffff;
    border-left: 6px solid #2563eb;
    padding: 24px;
    border-radius: 6px;
    text-align: center;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}
.metric-val {
    font-size: 30px;
    font-weight: 800;
    color: #000000 !important;
}
.metric-lbl {
    font-size: 12px;
    letter-spacing: 1px;
    font-weight: 700;
    color: #000000 !important;
}

/* CONTENT CARDS */
.content-card {
    background-color: #ffffff;
    padding: 26px;
    border-radius: 6px;
    border: 1px solid #e5e7eb;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    margin-bottom: 24px;
}

/* TABLE TEXT */
thead tr th, tbody tr td {
    color: #000000 !important;
}
</style>
""", unsafe_allow_html=True)

# =========================================================
# DATA ENGINE
# =========================================================
@st.cache_data(show_spinner=False)
def load_data(file):
    xl = pd.ExcelFile(file)
    return {s: xl.parse(s) for s in xl.sheet_names}, xl.sheet_names

def process_data(df):
    df.columns = df.columns.str.strip()
    df = df.fillna(0)

    df["EBIT"] = df["EBITDA"] - df["Depreciation"]
    df["NOPAT"] = df["EBIT"] * (1 - df["Tax_Rate"])
    df["FCFF"] = df["NOPAT"] + df["Depreciation"] - df["CapEx"] - df["Change_in_WC"]

    market_cap = df["Avg_Price"] * df["Shares_Outstanding"]
    df["Enterprise_Value"] = market_cap + df["Total_Debt"] - df["Cash_Equivalents"]

    df["ROE"] = np.where(df["Total_Equity"] != 0,
                         df["Net_Income"] / df["Total_Equity"], 0)
    df["PE"] = np.where(df["Net_Income"] != 0,
                        df["Avg_Price"] /
                        (df["Net_Income"] / df["Shares_Outstanding"]), 0)
    df["EV_EBITDA"] = np.where(df["EBITDA"] != 0,
                               df["Enterprise_Value"] / df["EBITDA"], 0)
    df["PB_Ratio"] = np.where(df["Total_Equity"] != 0,
                              market_cap / df["Total_Equity"], 0)
    return df

# =========================================================
# WACC ENGINE
# =========================================================
def calculate_wacc_dynamic(row):
    rf = row["Risk_Free_Rate"]
    rm = row["Market_Return"]
    beta = row["Beta"]
    ke = rf + beta * (rm - rf)

    debt = row["Total_Debt"]
    interest = row["Interest_Expense"]
    tax_rate = row["Tax_Rate"]

    if debt > 0:
        kd_pre_tax = interest / debt
        if kd_pre_tax > MAX_KD_PRE_TAX or kd_pre_tax < MIN_KD_PRE_TAX:
            kd_pre_tax = DEFAULT_KD_PRE_TAX
    else:
        kd_pre_tax = 0

    kd = kd_pre_tax * (1 - tax_rate)

    market_cap = row["Avg_Price"] * row["Shares_Outstanding"]
    total_val = market_cap + debt

    we = market_cap / total_val if total_val else 1
    wd = debt / total_val if total_val else 0

    wacc = we * ke + wd * kd
    return wacc, ke, kd

# =========================================================
# PROJECTIONS
# =========================================================
def project_financials(latest, wacc, growth_rate, tg, years=10):
    projections = []
    future_fcff = []

    revenue = latest["Revenue"]
    tax_rate = latest["Tax_Rate"]

    ebit_margin = latest["EBIT"] / revenue if revenue else 0
    dep_pct = latest["Depreciation"] / revenue if revenue else 0
    capex_pct = latest["CapEx"] / revenue if revenue else 0
    wc_pct = latest["Change_in_WC"] / revenue if revenue else 0

    current_growth = growth_rate

    for i in range(1, years + 1):
        if i > 5:
            fade = max(growth_rate - tg, 0) / 5
            current_growth -= fade

        revenue *= (1 + current_growth)
        ebit = revenue * ebit_margin
        nopat = ebit * (1 - tax_rate)
        dep = revenue * dep_pct
        capex = revenue * capex_pct
        wc = revenue * wc_pct

        fcff = nopat + dep - capex - wc
        pv = fcff / ((1 + wacc) ** i)

        future_fcff.append(fcff)
        projections.append({
            "Year": i,
            "Revenue": revenue,
            "EBIT": ebit,
            "FCFF": fcff,
            "PV FCFF": pv
        })

    safe_tg = min(tg, latest["Risk_Free_Rate"])
    if wacc <= safe_tg + TG_BUFFER:
        safe_tg = wacc - TG_BUFFER

    tv = (future_fcff[-1] * (1 + safe_tg)) / (wacc - safe_tg)
    pv_tv = tv / ((1 + wacc) ** years)

    return pd.DataFrame(projections), pv_tv

# =========================================================
# MAIN APP
# =========================================================
def main():
    st.sidebar.title("SENTINEL")
    uploaded = st.sidebar.file_uploader("Upload XLSX Model", type=["xlsx"])

    if not uploaded:
        st.info("Upload Excel file to begin valuation.")
        return

    raw, sheets = load_data(uploaded)
    ticker = st.sidebar.selectbox("Company", sheets)

    df = process_data(raw[ticker])
    latest = df.iloc[-1]

    wacc, ke, kd = calculate_wacc_dynamic(latest)
    proj_df, pv_tv = project_financials(
        latest,
        wacc,
        latest["Projected_Growth"],
        latest["Terminal_Growth"]
    )

    ev = proj_df["PV FCFF"].sum() + pv_tv
    equity = ev - latest["Total_Debt"] + latest["Cash_Equivalents"]
    target = equity / latest["Shares_Outstanding"]

    st.title(f"{ticker} – Institutional DCF Valuation")

    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='metric-card'><div class='metric-lbl'>Target Price</div><div class='metric-val'>₹ {target:,.2f}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='metric-card'><div class='metric-lbl'>WACC</div><div class='metric-val'>{wacc:.2%}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='metric-card'><div class='metric-lbl'>Terminal Value %</div><div class='metric-val'>{(pv_tv/ev)*100:.1f}%</div></div>", unsafe_allow_html=True)

    fig = px.line(proj_df, x="Year", y=["Revenue", "FCFF"], markers=True)
    fig.update_layout(**PLOTLY_BLACK)
    st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
