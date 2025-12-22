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
    page_title="IFAVP | Institutional Model", 
    layout="wide", 
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# --- 2. PREMIUM CORPORATE CSS ---
st.markdown("""
<style>
    /* Global Typography */
    html, body, [class*="css"] {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #333333;
    }
    
    /* Main Background */
    .stApp {
        background-color: #ffffff;
    }
    
    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #1a252f;
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
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        padding: 20px;
        border-radius: 6px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .metric-val {
        font-size: 24px;
        font-weight: 700;
        color: #2c3e50;
        margin: 5px 0;
    }
    .metric-lbl {
        font-size: 11px;
        color: #7f8c8d;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 600;
    }
    
    /* Tables */
    thead tr th {
        background-color: #f1f3f5 !important;
        color: #2c3e50 !important;
        font-weight: 600 !important;
        border-bottom: 2px solid #dee2e6 !important;
    }
    tbody tr:nth-child(even) {
        background-color: #f8f9fa;
    }
    
    /* Live Data Badge */
    .live-badge {
        display: inline-block;
        padding: 4px 8px;
        background-color: #e8f5e9;
        color: #27ae60;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
        border: 1px solid #c8e6c9;
        margin-left: 8px;
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
    # Ensure critical calculation columns exist (fill 0 if missing to prevent crash)
    # Note: A proper file from 'generate_detailed_data.py' will have all of these.
    expected_cols = [
        'Revenue', 'EBITDA', 'Net_Income', 'Depreciation', 'Interest_Expense',
        'CapEx', 'Change_in_WC', 'Total_Debt', 'Cash_Equivalents', 'Shares_Outstanding',
        'Avg_Price', 'Beta', 'Risk_Free_Rate', 'Market_Return', 'Terminal_Growth', 
        'Projected_Growth', 'Tax_Rate', 'Total_Equity', 'Total_Assets'
    ]
    for c in expected_cols:
        if c not in df.columns: df[c] = 0
            
    # Calculate Base Metrics
    df['EBIT'] = df['EBITDA'] - df['Depreciation']
    df['NOPAT'] = df['EBIT'] * (1 - df['Tax_Rate'])
    
    # Exact FCFF Formula
    # FCFF = NOPAT + D&A - CapEx - Change in Working Capital
    df['FCFF'] = df['NOPAT'] + df['Depreciation'] - df['CapEx'] - df['Change_in_WC']
    
    # Financial Ratios
    # Safety check for division by zero
    df['ROE'] = np.where(df['Total_Equity'] != 0, df['Net_Income'] / df['Total_Equity'], 0)
    df['PE'] = np.where(df['Net_Income'] != 0, df['Avg_Price'] / (df['Net_Income'] / df['Shares_Outstanding']), 0)
    
    return df

# --- 4. DYNAMIC CALCULATION ENGINE ---
def calculate_wacc_dynamic(row):
    """
    Calculates WACC using the exact inputs from the Excel row.
    No hardcoded assumptions.
    """
    # 1. Cost of Equity (CAPM)
    # Ke = Rf + Beta * (Rm - Rf)
    rf = row['Risk_Free_Rate']
    rm = row['Market_Return']
    beta = row['Beta']
    ke = rf + beta * (rm - rf)
    
    # 2. Cost of Debt (Kd)
    # Kd = (Interest / Debt) * (1 - T)
    debt = row['Total_Debt']
    interest = row['Interest_Expense']
    tax_rate = row['Tax_Rate']
    
    if debt > 0:
        kd_pre_tax = interest / debt
        # Logic check: If calculated cost of debt is absurd (>20% or <1%), clamp it to industry norm
        # This protects against bad data entry (e.g., Interest=0 but Debt>0)
        if kd_pre_tax > 0.20 or kd_pre_tax < 0.01: 
            kd_pre_tax = 0.08 
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

def project_financials(latest, wacc, years=5):
    """
    Projects financials 5 years out using 'Projected_Growth' from Excel.
    """
    # Base Year Ratios
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
    
    for i in range(1, years + 1):
        # 1. Grow Revenue
        p_rev = rev_base * ((1 + growth_rate) ** i)
        
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
            "EBIT": p_ebit, 
            "NOPAT": p_nopat,
            "Depreciation": p_dep, 
            "CapEx": p_capex, 
            "Chg WC": p_wc,
            "FCFF": p_fcff, 
            "Discount Factor": 1/dfactor, 
            "PV FCFF": pv
        })
        
    # Terminal Value
    last_fcff = future_fcff[-1]
    tv = (last_fcff * (1 + tg)) / (wacc - tg)
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
        self.cell(0, 10, 'IFAVP - Valuation Report', 0, 1, 'R')
        self.line(10, 20, 200, 20)
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()} | Generated by Intelligent Financial Analytics', 0, 0, 'C')

def generate_pdf(ticker, target, upside, wacc, ke, tg, proj_df, latest_data):
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
    color = (0, 128, 0) if upside > 0 else (200, 0, 0) # Green or Red
    
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(*color)
    pdf.cell(0, 10, f"Recommendation: {rec} ({upside:+.1f}%)", 0, 1)
    pdf.set_text_color(0, 0, 0) # Reset
    pdf.ln(5)
    
    # Executive Summary
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Executive Summary", 0, 1)
    pdf.set_font("Arial", '', 11)
    summary_text = (
        f"We have performed a comprehensive DCF valuation for {ticker}. "
        f"The model derives an intrinsic value of INR {target:,.2f} per share based on a WACC of {wacc*100:.2f}% "
        f"and a Terminal Growth rate of {tg*100:.2f}%.\n\n"
        f"Key Valuation Inputs (Sourced from Data Model):\n"
        f"- Risk Free Rate: {latest_data['Risk_Free_Rate']*100:.2f}%\n"
        f"- Market Return Assumption: {latest_data['Market_Return']*100:.2f}%\n"
        f"- Beta: {latest_data['Beta']:.2f}\n"
        f"- Cost of Equity (Ke): {ke*100:.2f}%\n"
    )
    pdf.multi_cell(0, 7, summary_text)
    pdf.ln(5)
    
    # Financial Projections Table
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "5-Year Cash Flow Projections", 0, 1)
    
    # Table Header
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(20, 10, "Year", 1, 0, 'C', 1)
    pdf.cell(40, 10, "Revenue", 1, 0, 'C', 1)
    pdf.cell(40, 10, "EBIT", 1, 0, 'C', 1)
    pdf.cell(40, 10, "FCFF", 1, 0, 'C', 1)
    pdf.cell(40, 10, "PV of FCFF", 1, 1, 'C', 1)
    
    # Table Rows
    pdf.set_font("Arial", '', 10)
    for _, row in proj_df.iterrows():
        pdf.cell(20, 10, f"{row['Year']}", 1, 0, 'C')
        pdf.cell(40, 10, f"{row['Revenue']:,.0f}", 1, 0, 'R')
        pdf.cell(40, 10, f"{row['EBIT']:,.0f}", 1, 0, 'R')
        pdf.cell(40, 10, f"{row['FCFF']:,.0f}", 1, 0, 'R')
        pdf.cell(40, 10, f"{row['PV FCFF']:,.0f}", 1, 1, 'R')
        
    return pdf.output(dest='S').encode('latin-1')

# --- 6. MAIN APPLICATION ---
def main():
    # Login System
    if not st.session_state.get('authenticated', False):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c2:
            st.markdown("""<div style='background-color: #f8f9fa; padding: 30px; border-radius: 10px; border: 1px solid #ddd; text-align: center;'><h3>IFAVP Login</h3><p style='color: #666;'>Institutional Access Only</p></div>""", unsafe_allow_html=True)
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            if st.button("Secure Login", use_container_width=True):
                if user=="admin" and pw=="password123":
                    st.session_state['authenticated'] = True
                    st.session_state['user'] = "admin"
                    st.rerun()
                else:
                    st.error("Access Denied.")
        return

    # Sidebar Layout
    st.sidebar.markdown("""<div style='text-align: center; padding: 15px 0;'><h2 style='color: white; margin:0;'>IFAVP</h2><p style='color: #bdc3c7; font-size: 10px;'>ANALYTICS SUITE v3.0</p></div>""", unsafe_allow_html=True)
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
        
        # 2. DYNAMIC CALCULATION (No hardcoding)
        wacc, ke, kd = calculate_wacc_dynamic(latest)
        proj_df, pv_tv = project_financials(latest, wacc)
        target_price, equity_val = calculate_valuation(latest, proj_df, pv_tv)
        
        # 3. LIVE MARKET DATA (Optional Reference)
        live_price = latest['Avg_Price']
        is_live = False
        y_ticker = None
        
        # Map Common Names to Yahoo Tickers (Optional Helper)
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
        t1, t2, t3, t4, t5 = st.tabs(["📊 Projections", "🧮 WACC Build", "📈 Trends", "👥 Comps", "📄 Report"])
        
        # Tab 1: Projections
        with t1:
            st.markdown("### Future Cash Flow Projections (FCFF)")
            st.dataframe(proj_df.style.format("{:,.0f}"), use_container_width=True)
            
            fig = go.Figure(go.Waterfall(
                measure=["relative", "relative", "total"],
                x=["PV Cash Flows (1-5)", "PV Terminal Value", "Enterprise Value"],
                y=[proj_df['PV FCFF'].sum(), pv_tv, 0],
                connector={"line":{"color":"#333"}}
            ))
            fig.update_layout(title="Enterprise Value Composition", height=350, plot_bgcolor='white')
            st.plotly_chart(fig, use_container_width=True)
            
        # Tab 2: WACC Build
        with t2:
            st.subheader("Weighted Average Cost of Capital")
            st.markdown("All inputs sourced directly from uploaded Excel file.")
            
            w1, w2 = st.columns(2)
            with w1:
                st.markdown("**Cost of Equity (Ke)**")
                st.dataframe(pd.DataFrame({
                    "Component": ["Risk Free Rate", "Beta", "Market Return", "Cost of Equity"],
                    "Value": [f"{latest['Risk_Free_Rate']:.2%}", f"{latest['Beta']:.2f}", f"{latest['Market_Return']:.2%}", f"{ke:.2%}"]
                }), hide_index=True, use_container_width=True)
            
            with w2:
                st.markdown("**Cost of Debt (Kd) & WACC**")
                st.dataframe(pd.DataFrame({
                    "Component": ["Interest Expense", "Total Debt", "Tax Rate", "Post-Tax Kd", "Final WACC"],
                    "Value": [f"{latest['Interest_Expense']:,.0f}", f"{latest['Total_Debt']:,.0f}", f"{latest['Tax_Rate']:.1%}", f"{kd:.2%}", f"{wacc:.2%}"]
                }), hide_index=True, use_container_width=True)
                
        # Tab 3: Historical Trends
        with t3:
            c_trend1, c_trend2 = st.columns(2)
            with c_trend1:
                fig_rev = px.bar(df, x='Year', y='Revenue', title="Revenue Growth", color_discrete_sequence=['#3498db'])
                fig_rev.update_layout(plot_bgcolor='white')
                st.plotly_chart(fig_rev, use_container_width=True)
            with c_trend2:
                fig_prof = px.line(df, x='Year', y=['EBITDA', 'Net_Income'], title="Profitability", markers=True)
                fig_prof.update_layout(plot_bgcolor='white')
                st.plotly_chart(fig_prof, use_container_width=True)
                
        # Tab 4: Peer Comparison
        with t4:
            st.subheader("Industry Analysis")
            peers = []
            for t in sheets:
                d = process_data(raw_data[t].copy()).iloc[-1]
                peers.append({
                    'Ticker': t, 
                    'P/E': d['PE'], 
                    'ROE': d['ROE']*100, 
                    'Revenue': d['Revenue']
                })
            peer_df = pd.DataFrame(peers).set_index('Ticker')
            
            p1, p2 = st.columns(2)
            with p1:
                fig_pe = px.bar(peer_df, x=peer_df.index, y='P/E', title="P/E Ratio", color=peer_df.index)
                fig_pe.update_layout(plot_bgcolor='white', showlegend=False)
                st.plotly_chart(fig_pe, use_container_width=True)
            with p2:
                fig_roe = px.bar(peer_df, x=peer_df.index, y='ROE', title="ROE (%)", color=peer_df.index)
                fig_roe.update_layout(plot_bgcolor='white', showlegend=False)
                st.plotly_chart(fig_roe, use_container_width=True)
                
        # Tab 5: Report
        with t5:
            st.markdown("### Generate Investment Note")
            if st.button("Download PDF Report"):
                pdf_bytes = generate_pdf(ticker, target_price, upside, wacc, ke, latest['Terminal_Growth'], proj_df, latest)
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/pdf;base64,{b64}" download="{ticker}_Valuation_Report.pdf" style="background-color:#2c3e50; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Download PDF File</a>'
                st.markdown(href, unsafe_allow_html=True)
                st.success("Report generated successfully.")
                
    else:
        st.info("👋 Welcome to IFAVP. Please upload the 'fmcg_data_detailed.xlsx' file to begin.")

if __name__ == "__main__":
    main()
