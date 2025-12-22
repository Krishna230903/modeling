import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
from datetime import datetime
import yfinance as yf

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="IFAVP | Institutional Analytics", 
    layout="wide", 
    page_icon="📊",
    initial_sidebar_state="expanded"
)

# --- 2. PREMIUM CORPORATE CSS (Black Text Enforcement) ---
st.markdown("""
<style>
    /* Global Typography */
    html, body, [class*="css"] {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #000000; /* Pure Black */
    }
    
    /* Main Background */
    .stApp {
        background-color: #f4f7f6; 
    }
    
    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #2c3e50;
    }
    section[data-testid="stSidebar"] h1, 
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3, 
    section[data-testid="stSidebar"] label, 
    section[data-testid="stSidebar"] .stMarkdown, 
    section[data-testid="stSidebar"] p {
        color: #ecf0f1 !important;
    }
    
    /* Metric Cards */
    .metric-card {
        background-color: #ffffff;
        border-left: 5px solid #3498db;
        padding: 20px;
        border-radius: 8px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 15px rgba(0,0,0,0.1);
    }
    .metric-val {
        font-size: 28px;
        font-weight: 700;
        color: #000000; /* Pure Black */
        margin: 5px 0;
    }
    .metric-lbl {
        font-size: 13px;
        color: #000000; /* Pure Black */
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 700;
    }
    
    /* Custom Content Cards */
    .content-card {
        background-color: #ffffff;
        padding: 25px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    
    /* Login Page Styling */
    .login-container {
        background-color: #ffffff;
        padding: 40px;
        border-radius: 12px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        text-align: center;
        max-width: 400px;
        margin: 50px auto;
        border-top: 5px solid #2c3e50;
    }
    .login-container h2 {
        color: #000000 !important;
    }
    .login-container p {
        color: #000000 !important;
    }
    
    /* Tables */
    thead tr th {
        background-color: #ecf0f1 !important;
        color: #000000 !important; /* Pure Black */
        font-weight: 800 !important;
        border-bottom: 2px solid #bdc3c7 !important;
    }
    tbody tr:nth-child(even) {
        background-color: #f8f9fa;
    }
    tbody tr td {
        color: #000000 !important;
    }
    
    /* Live Data Badge */
    .live-badge {
        display: inline-block;
        padding: 6px 12px;
        background-color: #e8f5e9;
        color: #2e7d32;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 700;
        border: 1px solid #a5d6a7;
        margin-left: 10px;
        vertical-align: middle;
    }
    
    /* Headers */
    h1, h2, h3, h4 {
        color: #000000; /* Pure Black */
        font-weight: 800;
        letter-spacing: -0.5px;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. DATA ENGINE ---
@st.cache_data
def load_data(file):
    try:
        xl = pd.ExcelFile(file)
        return {sheet: xl.parse(sheet) for sheet in xl.sheet_names}, xl.sheet_names
    except Exception as e:
        return None, []

def process_data(df):
    # Standardize column names (strip whitespace)
    df.columns = df.columns.str.strip()
    
    # Critical columns needed for valuation based on PDF logic
    expected_cols = [
        'Revenue', 'EBITDA', 'Net_Income', 'Depreciation', 'Interest_Expense',
        'CapEx', 'Change_in_WC', 'Total_Debt', 'Cash_Equivalents', 'Shares_Outstanding',
        'Avg_Price', 'Beta', 'Risk_Free_Rate', 'Market_Return', 'Terminal_Growth', 
        'Projected_Growth', 'Tax_Rate', 'Total_Equity', 'Total_Assets'
    ]
    
    # 1. Ensure all columns exist
    for c in expected_cols:
        if c not in df.columns: df[c] = 0
            
    # 2. ROBUST CLEANING: Remove commas and convert to float
    for col in df.columns:
        if df[col].dtype == 'object': 
            try:
                df[col] = df[col].astype(str).str.replace(',', '').replace('-', '0')
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            except:
                pass 
        elif pd.api.types.is_numeric_dtype(df[col]):
             df[col] = df[col].fillna(0)

    # 3. Calculate Base Metrics (FCFF)
    df['EBIT'] = df['EBITDA'] - df['Depreciation']
    df['NOPAT'] = df['EBIT'] * (1 - df['Tax_Rate'])
    
    # Exact FCFF Formula: NOPAT + D&A - CapEx - Change in Working Capital
    df['FCFF'] = df['NOPAT'] + df['Depreciation'] - df['CapEx'] - df['Change_in_WC']
    
    # Financial Ratios
    df['ROE'] = np.where(df['Total_Equity'] != 0, df['Net_Income'] / df['Total_Equity'], 0)
    df['PE'] = np.where(df['Net_Income'] != 0, df['Avg_Price'] / (df['Net_Income'] / df['Shares_Outstanding']), 0)
    
    # Enterprise Value for Multiples
    market_cap = df['Avg_Price'] * df['Shares_Outstanding']
    df['Enterprise_Value'] = market_cap + df['Total_Debt'] - df['Cash_Equivalents']
    df['EV_EBITDA'] = np.where(df['EBITDA'] != 0, df['Enterprise_Value'] / df['EBITDA'], 0)
    df['PB_Ratio'] = np.where(df['Total_Equity'] != 0, market_cap / df['Total_Equity'], 0)

    return df

# --- 4. DYNAMIC CALCULATION ENGINE ---
def calculate_wacc_dynamic(row):
    """
    Calculates WACC using the exact inputs from the Excel row.
    Logic aligns with PDF methodology (CAPM for Ke).
    """
    # 1. Cost of Equity (CAPM)
    rf = row['Risk_Free_Rate']
    rm = row['Market_Return']
    beta = row['Beta']
    ke = rf + beta * (rm - rf)
    
    # 2. Cost of Debt (Kd)
    debt = row['Total_Debt']
    interest = row['Interest_Expense']
    tax_rate = row['Tax_Rate']
    
    if debt > 0:
        kd_pre_tax = interest / debt
        if kd_pre_tax > 0.20 or kd_pre_tax < 0.01: kd_pre_tax = 0.08 
    else:
        kd_pre_tax = 0.0
        
    kd = kd_pre_tax * (1 - tax_rate)
    
    # 3. Weights
    market_cap = row['Avg_Price'] * row['Shares_Outstanding']
    total_val = market_cap + debt
    
    we = market_cap / total_val if total_val > 0 else 1
    wd = debt / total_val if total_val > 0 else 0
    
    wacc = (we * ke) + (wd * kd)
    return wacc, ke, kd

def project_financials(latest, wacc, years=10):
    """
    Projects financials 10 years out (standard for quality FMCG).
    Uses 'Projected_Growth' from Excel for explicit forecast period.
    """
    rev_base = latest['Revenue']
    growth_rate = latest['Projected_Growth']
    tg = latest['Terminal_Growth']
    tax_rate = latest['Tax_Rate']
    
    # Ratios as % of Revenue
    ebit_margin = latest['EBIT'] / rev_base if rev_base > 0 else 0
    dep_pct = latest['Depreciation'] / rev_base if rev_base > 0 else 0
    capex_pct = latest['CapEx'] / rev_base if rev_base > 0 else 0
    wc_pct = latest['Change_in_WC'] / rev_base if rev_base > 0 else 0
    
    projections = []
    future_fcff = []
    
    current_growth = growth_rate
    
    for i in range(1, years + 1):
        # Linearly fade growth after year 5 towards terminal growth
        if i > 5:
            current_growth = current_growth - ((growth_rate - tg) / 5)
            
        # 1. Grow Revenue
        if i == 1:
            p_rev = rev_base * (1 + current_growth)
        else:
            p_rev = projections[-1]['Revenue'] * (1 + current_growth)
        
        # 2. Apply Margins
        p_ebit = p_rev * ebit_margin
        p_nopat = p_ebit * (1 - tax_rate)
        p_dep = p_rev * dep_pct
        p_capex = p_rev * capex_pct
        p_wc = p_rev * wc_pct
        
        # 3. Calculate FCFF
        p_fcff = p_nopat + p_dep - p_capex - p_wc
        
        # 4. Discount to PV
        dfactor = (1 + wacc) ** i
        pv = p_fcff / dfactor
        future_fcff.append(p_fcff)
        
        projections.append({
            "Year": i, 
            "Revenue": p_rev, 
            "Growth %": current_growth * 100,
            "EBIT": p_ebit, 
            "NOPAT": p_nopat,
            "Depreciation": p_dep, 
            "CapEx": p_capex, 
            "Chg WC": p_wc,
            "FCFF": p_fcff, 
            "Discount Factor": 1/dfactor, 
            "PV FCFF": pv
        })
        
    # Terminal Value (Gordon Growth Method)
    last_fcff = future_fcff[-1]
    safe_tg = min(tg, latest['Risk_Free_Rate'])
    
    tv = (last_fcff * (1 + safe_tg)) / (wacc - safe_tg)
    pv_tv = tv / ((1 + wacc) ** years)
    
    return pd.DataFrame(projections), pv_tv

def calculate_valuation(latest, proj_df, pv_tv):
    enterprise_val = proj_df['PV FCFF'].sum() + pv_tv
    equity_val = enterprise_val - latest['Total_Debt'] + latest['Cash_Equivalents']
    target_price = equity_val / latest['Shares_Outstanding']
    return target_price, equity_val

# --- 5. REPORTING ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'IFAVP - Institutional Valuation Report', 0, 1, 'R')
        self.line(10, 20, 200, 20)
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()} | Generated by Intelligent Financial Analytics', 0, 0, 'C')

def generate_pdf(ticker, target, upside, wacc, ke, tg, proj_df, latest_data, peer_df, hist_df):
    pdf = PDFReport()
    pdf.add_page()
    
    # Title
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"Equity Research Report: {ticker}", 0, 1)
    pdf.set_font("Arial", '', 10)
    pdf.cell(0, 10, f"Valuation Date: {datetime.now().strftime('%Y-%m-%d')}", 0, 1)
    pdf.ln(5)
    
    # Recommendation Section
    rec = "BUY" if upside > 15 else "ACCUMULATE" if upside > 0 else "HOLD" if upside > -10 else "SELL"
    color = (0, 128, 0) if upside > 0 else (200, 0, 0)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(*color)
    pdf.cell(0, 10, f"Recommendation: {rec} ({upside:+.1f}%)", 0, 1)
    pdf.set_text_color(0, 0, 0) # Reset
    pdf.ln(5)
    
    # Executive Summary
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Valuation Summary (DCF Methodology)", 0, 1)
    pdf.set_font("Arial", '', 11)
    summary_text = (
        f"This report presents a comprehensive Discounted Cash Flow (DCF) valuation for {ticker}. "
        f"Based on a 10-year projection period and the Free Cash Flow to Firm (FCFF) approach, "
        f"we derive an intrinsic value of INR {target:,.2f} per share. "
        f"This implies a potential upside of {upside:+.1f}% against the current market price."
    )
    pdf.multi_cell(0, 7, summary_text)
    pdf.ln(5)
    
    # WACC & Assumptions Table
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Key Model Assumptions (Sourced from Data)", 0, 1)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(60, 10, "Metric", 1, 0, 'L', 1)
    pdf.cell(40, 10, "Value", 1, 1, 'C', 1)
    
    pdf.set_font("Arial", '', 10)
    assumptions = [
        ("WACC (Calculated)", f"{wacc*100:.2f}%"),
        ("Cost of Equity (Ke)", f"{ke*100:.2f}%"),
        ("Terminal Growth Rate", f"{tg*100:.2f}%"),
        ("Beta", f"{latest_data['Beta']:.2f}"),
        ("Risk Free Rate", f"{latest_data['Risk_Free_Rate']*100:.2f}%"),
        ("Market Return", f"{latest_data['Market_Return']*100:.2f}%")
    ]
    
    for metric, val in assumptions:
        pdf.cell(60, 10, metric, 1, 0, 'L')
        pdf.cell(40, 10, val, 1, 1, 'C')
    pdf.ln(5)
    
    # Comparable Company Analysis Table
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Comparable Company Analysis (CCA)", 0, 1)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(230, 230, 230)
    # Header
    cols = ["Ticker", "P/E", "EV/EBITDA", "ROE (%)", "Revenue (Cr)"]
    widths = [40, 30, 30, 30, 40]
    for i, c in enumerate(cols):
        pdf.cell(widths[i], 10, c, 1, 0, 'C', 1)
    pdf.ln()
    
    # Rows
    pdf.set_font("Arial", '', 10)
    for index, row in peer_df.iterrows():
        pdf.cell(widths[0], 10, str(index), 1, 0, 'C')
        pdf.cell(widths[1], 10, f"{row['P/E Ratio']:.1f}x", 1, 0, 'C')
        pdf.cell(widths[2], 10, f"{row['EV/EBITDA']:.1f}x", 1, 0, 'C')
        pdf.cell(widths[3], 10, f"{row['ROE (%)']:.1f}%", 1, 0, 'C')
        pdf.cell(widths[4], 10, f"{row['Revenue (Cr)']:,.0f}", 1, 1, 'C')
    
    pdf.ln(5)
    
    # Historical Data Table (NEW SECTION)
    pdf.add_page()
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Historical Financial Data (Uploaded)", 0, 1)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(230, 230, 230)
    hist_cols = ["Year", "Revenue", "EBITDA", "Net Income", "CapEx"]
    hist_widths = [30, 40, 40, 40, 40]
    
    for i, h in enumerate(hist_cols):
        pdf.cell(hist_widths[i], 10, h, 1, 0, 'C', 1)
    pdf.ln()
    
    pdf.set_font("Arial", '', 10)
    for index, row in hist_df.iterrows():
        try:
            year_val = str(int(row['Year']))
        except:
            year_val = str(row['Year'])
            
        pdf.cell(hist_widths[0], 10, year_val, 1, 0, 'C')
        pdf.cell(hist_widths[1], 10, f"{row['Revenue']:,.0f}", 1, 0, 'R')
        pdf.cell(hist_widths[2], 10, f"{row['EBITDA']:,.0f}", 1, 0, 'R')
        pdf.cell(hist_widths[3], 10, f"{row['Net_Income']:,.0f}", 1, 0, 'R')
        pdf.cell(hist_widths[4], 10, f"{row['CapEx']:,.0f}", 1, 1, 'R')
    pdf.ln(5)

    # Projections Table
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Cash Flow Projections (Next 5 Years)", 0, 1)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(20, 10, "Year", 1, 0, 'C', 1)
    pdf.cell(45, 10, "Revenue", 1, 0, 'C', 1)
    pdf.cell(45, 10, "EBIT", 1, 0, 'C', 1)
    pdf.cell(45, 10, "FCFF", 1, 0, 'C', 1)
    pdf.cell(35, 10, "PV of FCFF", 1, 1, 'C', 1)
    
    pdf.set_font("Arial", '', 10)
    for index, row in proj_df.head(5).iterrows():
        pdf.cell(20, 10, f"{row['Year']}", 1, 0, 'C')
        pdf.cell(45, 10, f"{row['Revenue']:,.0f}", 1, 0, 'R')
        pdf.cell(45, 10, f"{row['EBIT']:,.0f}", 1, 0, 'R')
        pdf.cell(45, 10, f"{row['FCFF']:,.0f}", 1, 0, 'R')
        pdf.cell(35, 10, f"{row['PV FCFF']:,.0f}", 1, 1, 'R')
        
    return pdf.output(dest='S').encode('latin-1')

# --- 6. MAIN APPLICATION ---
def main():
    # Login System
    if not st.session_state.get('authenticated', False):
        # Improved Login UI
        c1, c2, c3 = st.columns([1, 1, 1])
        with c2:
            st.markdown("""
            <div class="login-container">
                <h2 style="color:#000000; font-weight:700;">IFAVP Portal</h2>
                <p style="color:#000000; margin-bottom:20px;">Institutional Financial Analytics System</p>
                <div style="text-align:left; margin-bottom:10px; color:#000000; font-weight:600;">Secure Login</div>
            """, unsafe_allow_html=True)
            
            user = st.text_input("Username", placeholder="admin")
            pw = st.text_input("Password", type="password", placeholder="••••••••")
            
            if st.button("Access Dashboard", use_container_width=True):
                if user=="admin" and pw=="password123":
                    st.session_state['authenticated'] = True
                    st.session_state['user'] = "admin"
                    st.rerun()
                else:
                    st.error("Access Denied: Invalid Credentials")
            
            st.markdown("</div>", unsafe_allow_html=True)
        return

    # Sidebar Layout
    st.sidebar.markdown("""<div style='text-align: center; padding: 20px 0;'><h2 style='color: white; margin:0; letter-spacing:1px;'>IFAVP</h2><p style='color: #bdc3c7; font-size: 11px; margin-top:5px;'>ANALYTICS SUITE v4.0</p></div>""", unsafe_allow_html=True)
    st.sidebar.markdown(f"**Analyst:** {st.session_state['user']}")
    if st.sidebar.button("Log Out"):
        st.session_state['authenticated'] = False
        st.session_state['user'] = None
        st.rerun()
        
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📂 Data Management")
    uploaded_file = st.sidebar.file_uploader("Upload Data Model (XLSX)", type=['xlsx'])
    
    # Main Dashboard Logic
    if uploaded_file:
        raw_data, sheets = load_data(uploaded_file)
        if not raw_data: return
        
        st.sidebar.markdown("### 🏢 Entity Focus")
        ticker = st.sidebar.selectbox("Select Company", sheets)
        
        # 1. READ & PROCESS DATA
        df = process_data(raw_data[ticker].copy())
        latest = df.iloc[-1]
        
        # 2. DYNAMIC CALCULATION
        wacc, ke, kd = calculate_wacc_dynamic(latest)
        proj_df, pv_tv = project_financials(latest, wacc)
        target_price, equity_val = calculate_valuation(latest, proj_df, pv_tv)
        
        # 3. LIVE MARKET DATA
        live_price = latest['Avg_Price']
        is_live = False
        y_ticker = None
        TICKER_MAP = {'HUL': 'HINDUNILVR.NS', 'ITC': 'ITC.NS', 'COLPAL': 'COLPAL.NS', 'COLGATE': 'COLPAL.NS'}
        y_ticker = TICKER_MAP.get(ticker.upper(), f"{ticker}.NS")
        
        try:
            stock = yf.Ticker(y_ticker)
            fast_info = stock.fast_info
            if fast_info.last_price:
                live_price = fast_info.last_price
                is_live = True
        except:
            pass
            
        upside = (target_price - live_price)/live_price * 100
        
        # --- HEADER SECTION ---
        st.title(f"{ticker} Valuation Analysis")
        st.markdown(f"**Valuation Date:** {datetime.now().strftime('%d %B %Y')} | **Currency:** INR (Crores)")
        
        if is_live:
            st.markdown(f'<div class="live-badge">⚡ Live Market Price Active ({y_ticker})</div>', unsafe_allow_html=True)
        else:
            st.warning("Using Book Price (Live data unavailable)")
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # --- KPI CARDS ---
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f'<div class="metric-card"><div class="metric-lbl">Target Value (Intrinsic)</div><div class="metric-val">₹ {target_price:,.2f}</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="metric-card"><div class="metric-lbl">Current Price</div><div class="metric-val">₹ {live_price:,.2f}</div></div>', unsafe_allow_html=True)
        
        up_color = "#27ae60" if upside > 0 else "#c0392b"
        c3.markdown(f'<div class="metric-card" style="border-left: 5px solid {up_color};"><div class="metric-lbl">Implied Upside</div><div class="metric-val" style="color:{up_color}">{upside:+.2f}%</div></div>', unsafe_allow_html=True)
        
        c4.markdown(f'<div class="metric-card"><div class="metric-lbl">WACC (Calculated)</div><div class="metric-val">{wacc:.1%}</div></div>', unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # --- TABS ---
        t1, t2, t3, t4, t5 = st.tabs(["📊 Projections", "🧮 WACC Build", "📈 Trends", "👥 Comparable Analysis", "📄 Report"])
        
        # Tab 1: Projections
        with t1:
            st.markdown("### Future Cash Flow Projections (10 Years)")
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            st.dataframe(proj_df.style.format("{:,.0f}"), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            fig = go.Figure(go.Waterfall(
                measure=["relative", "relative", "total"],
                x=["PV Cash Flows (1-10)", "PV Terminal Value", "Enterprise Value"],
                y=[proj_df['PV FCFF'].sum(), pv_tv, 0],
                connector={"line":{"color":"#000000"}}
            ))
            fig.update_layout(title="Enterprise Value Composition", height=350, plot_bgcolor='white', paper_bgcolor='white', font={'color': '#000000'})
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        # Tab 2: WACC Build
        with t2:
            st.subheader("Weighted Average Cost of Capital")
            st.markdown("All inputs sourced directly from uploaded Excel file.")
            
            w1, w2 = st.columns(2)
            with w1:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                st.markdown("**Cost of Equity (Ke)**")
                st.dataframe(pd.DataFrame({
                    "Component": ["Risk Free Rate", "Beta", "Market Return", "Cost of Equity"],
                    "Value": [f"{latest['Risk_Free_Rate']:.2%}", f"{latest['Beta']:.2f}", f"{latest['Market_Return']:.2%}", f"{ke:.2%}"]
                }), hide_index=True, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with w2:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                st.markdown("**Cost of Debt (Kd) & WACC**")
                st.dataframe(pd.DataFrame({
                    "Component": ["Interest Expense", "Total Debt", "Tax Rate", "Post-Tax Kd", "Final WACC"],
                    "Value": [f"{latest['Interest_Expense']:,.0f}", f"{latest['Total_Debt']:,.0f}", f"{latest['Tax_Rate']:.1%}", f"{kd:.2%}", f"{wacc:.2%}"]
                }), hide_index=True, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
        # Tab 3: Historical Trends
        with t3:
            c_trend1, c_trend2 = st.columns(2)
            with c_trend1:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                fig_rev = px.bar(df, x='Year', y='Revenue', title="Revenue Growth", color_discrete_sequence=['#3498db'])
                fig_rev.update_layout(plot_bgcolor='white', paper_bgcolor='white', font={'color': '#000000'})
                st.plotly_chart(fig_rev, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            with c_trend2:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                fig_prof = px.line(df, x='Year', y=['EBITDA', 'Net_Income'], title="Profitability", markers=True)
                fig_prof.update_layout(plot_bgcolor='white', paper_bgcolor='white', font={'color': '#000000'})
                st.plotly_chart(fig_prof, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
        # Tab 4: Peer Comparison
        with t4:
            st.subheader("Comparable Company Analysis (CCA)")
            st.markdown("Benchmarking key valuation multiples and operating metrics across the peer group.")
            
            # Aggregate Peer Data
            peers = []
            for t in sheets:
                d = process_data(raw_data[t].copy()).iloc[-1]
                ebitda_margin = (d['EBITDA'] / d['Revenue']) * 100 if d['Revenue'] > 0 else 0
                net_margin = (d['Net_Income'] / d['Revenue']) * 100 if d['Revenue'] > 0 else 0
                
                peers.append({
                    'Ticker': t, 
                    'P/E Ratio': d['PE'], 
                    'EV/EBITDA': d['EV_EBITDA'],
                    'P/B Ratio': d['PB_Ratio'],
                    'ROE (%)': d['ROE']*100, 
                    'EBITDA Margin (%)': ebitda_margin,
                    'Net Profit Margin (%)': net_margin,
                    'Revenue (Cr)': d['Revenue']
                })
            
            peer_df = pd.DataFrame(peers).set_index('Ticker')
            
            # Display Comparative Table
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            st.dataframe(peer_df.style.format("{:.2f}").background_gradient(cmap="Blues"), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Visual Comparison Charts
            st.markdown("### Valuation Multiples Comparison")
            col_v1, col_v2 = st.columns(2)
            
            with col_v1:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                fig_pe = px.bar(peer_df, x=peer_df.index, y='P/E Ratio', title="Price to Earnings (P/E)", color=peer_df.index, text_auto='.1f')
                fig_pe.update_layout(plot_bgcolor='white', paper_bgcolor='white', showlegend=False, font={'color': '#000000'})
                st.plotly_chart(fig_pe, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
            with col_v2:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                fig_ev = px.bar(peer_df, x=peer_df.index, y='EV/EBITDA', title="EV / EBITDA", color=peer_df.index, text_auto='.1f')
                fig_ev.update_layout(plot_bgcolor='white', paper_bgcolor='white', showlegend=False, font={'color': '#000000'})
                st.plotly_chart(fig_ev, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown("### Profitability & Efficiency Comparison")
            col_p1, col_p2 = st.columns(2)
            
            with col_p1:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                fig_roe = px.bar(peer_df, x=peer_df.index, y='ROE (%)', title="Return on Equity (ROE)", color=peer_df.index, text_auto='.1f')
                fig_roe.update_layout(plot_bgcolor='white', paper_bgcolor='white', showlegend=False, font={'color': '#000000'})
                st.plotly_chart(fig_roe, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
            with col_p2:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                fig_marg = go.Figure()
                fig_marg.add_trace(go.Bar(x=peer_df.index, y=peer_df['EBITDA Margin (%)'], name='EBITDA Margin'))
                fig_marg.add_trace(go.Bar(x=peer_df.index, y=peer_df['Net Profit Margin (%)'], name='Net Margin'))
                fig_marg.update_layout(title="Operating Margins", barmode='group', plot_bgcolor='white', paper_bgcolor='white', font={'color': '#000000'})
                st.plotly_chart(fig_marg, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
        # Tab 5: Report
        with t5:
            st.markdown("### Generate Investment Note")
            if st.button("Download PDF Report"):
                pdf_bytes = generate_pdf(ticker, target_price, upside, wacc, ke, latest['Terminal_Growth'], proj_df, latest, peer_df, df)
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/pdf;base64,{b64}" download="{ticker}_Valuation_Report.pdf" style="background-color:#2c3e50; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Download PDF File</a>'
                st.markdown(href, unsafe_allow_html=True)
                st.success("Report generated successfully.")
                
    else:
        st.info("👋 Welcome to IFAVP. Please upload the 'fmcg_data_detailed.xlsx' file to begin.")

if __name__ == "__main__":
    main()
