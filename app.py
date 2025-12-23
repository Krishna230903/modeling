import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
from datetime import datetime
import yfinance as yf
import io

# --- CONSTANTS ---
MAX_KD_PRE_TAX = 0.20
MIN_KD_PRE_TAX = 0.01
DEFAULT_KD_PRE_TAX = 0.08
TERMINAL_VALUE_WARNING_THRESHOLD = 70.0
LEVERAGE_WARNING_THRESHOLD = 3.0
TG_BUFFER = 0.002 # 0.2% buffer for WACC > TG
MACRO_GROWTH_CEILING = 0.05 # 5% hard ceiling for terminal growth

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="Sentinel | Institutional Analytics", 
    layout="wide", 
    initial_sidebar_state="expanded",
    page_icon="🛡️"
)

# --- 2. UI/UX DESIGN SYSTEM (CSS) ---
st.markdown("""
<style>
    /* IMPORT FONTS */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=Playfair+Display:wght@700&family=Roboto+Mono:wght@400;700&display=swap');

    /* GLOBAL VARIABLES */
    :root {
        --primary-color: #2c3e50;
        --accent-color: #2980b9;
        --success-color: #27ae60;
        --bg-color: #f8fafc;
        --card-bg: #ffffff;
        --text-color: #1e293b;
    }

    /* BASE STYLES */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        color: var(--text-color) !important;
        background-color: var(--bg-color);
    }

    /* SIDEBAR STYLING */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
        border-right: 1px solid #334155;
    }
    section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {
        color: #f8fafc !important;
    }
    section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] label {
        color: #94a3b8 !important;
    }
    
    /* CUSTOM CARDS */
    .metric-card {
        background-color: var(--card-bg);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        transition: all 0.3s ease;
        text-align: center;
        height: 100%;
        position: relative;
        overflow: hidden;
    }
    
    .metric-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        border-color: var(--accent-color);
    }
    
    .metric-lbl {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: #64748b !important;
        font-weight: 600;
        margin-bottom: 8px;
    }
    
    .metric-val {
        font-family: 'Roboto Mono', monospace;
        font-size: 1.75rem;
        font-weight: 700;
        color: var(--primary-color) !important;
    }

    /* CONTENT CONTAINERS */
    .content-card {
        background-color: var(--card-bg);
        padding: 30px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);
        margin-bottom: 24px;
    }

    /* HEADERS */
    h1, h2, h3 {
        font-family: 'Playfair Display', serif;
        color: var(--primary-color) !important;
        font-weight: 700;
    }

    /* LOGIN SCREEN */
    .login-container {
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(10px);
        padding: 60px 40px;
        border-radius: 16px;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        text-align: center;
        max-width: 400px;
        margin: 80px auto;
        border: 1px solid #e2e8f0;
    }
    .login-title {
        font-family: 'Playfair Display', serif;
        font-size: 2.5rem;
        color: var(--primary-color);
        margin-bottom: 0.5rem;
    }
    .login-subtitle {
        color: #64748b;
        font-size: 0.875rem;
        margin-bottom: 2rem;
        text-transform: uppercase;
        letter-spacing: 2px;
    }

    /* BUTTONS */
    .stButton button {
        background-color: var(--primary-color);
        color: white !important;
        font-weight: 600;
        border-radius: 8px;
        padding: 0.6rem 1.2rem;
        border: none;
        transition: background 0.2s;
        width: 100%;
    }
    .stButton button:hover {
        background-color: #34495e;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    
    /* TABLES */
    thead tr th {
        background-color: #f1f5f9 !important;
        color: #334155 !important;
        font-weight: 700 !important;
    }

    /* LIVE BADGE */
    .live-badge {
        background-color: #dcfce7;
        color: #166534 !important;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 700;
        border: 1px solid #86efac;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .live-dot {
        width: 8px;
        height: 8px;
        background-color: #166534;
        border-radius: 50%;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
</style>
""", unsafe_allow_html=True)

# --- 3. HELPER FUNCTIONS ---

def generate_excel_template():
    """Generates an in-memory Excel file with dummy data."""
    buffer = io.BytesIO()
    
    # Dummy data ensuring all required columns are present
    data = {
        'Year': [2023, 2024],
        'Revenue': [50000, 55000],
        'EBITDA': [12000, 13200],
        'Net_Income': [8000, 8800],
        'Depreciation': [1000, 1100],
        'Interest_Expense': [200, 180],
        'CapEx': [1500, 1650],
        'Change_in_WC': [500, 550],
        'Total_Debt': [2000, 1800],
        'Cash_Equivalents': [4000, 4500],
        'Shares_Outstanding': [235, 235],
        'Avg_Price': [2450, 2600],
        'Beta': [0.65, 0.65],
        'Risk_Free_Rate': [0.07, 0.07],
        'Market_Return': [0.12, 0.12],
        'Terminal_Growth': [0.05, 0.05],
        'Projected_Growth': [0.10, 0.10],
        'Tax_Rate': [0.25, 0.25],
        'Total_Equity': [45000, 50000],
        'Total_Assets': [60000, 66000],
        'Current_Assets': [15000, 16500],
        'Current_Liabilities': [8000, 8800]
    }
    
    df = pd.DataFrame(data)
    
    # Use pandas to write the Excel file to the buffer
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='TEMPLATE_DATA', index=False)
        
    buffer.seek(0)
    return buffer

@st.cache_data(show_spinner=False)
def load_data(file):
    try:
        xl = pd.ExcelFile(file)
        return {sheet: xl.parse(sheet) for sheet in xl.sheet_names}, xl.sheet_names
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None, []

def process_data(df):
    df.columns = df.columns.str.strip()
    expected_cols = [
        'Revenue', 'EBITDA', 'Net_Income', 'Depreciation', 'Interest_Expense',
        'CapEx', 'Change_in_WC', 'Total_Debt', 'Cash_Equivalents', 'Shares_Outstanding',
        'Avg_Price', 'Beta', 'Risk_Free_Rate', 'Market_Return', 'Terminal_Growth', 
        'Projected_Growth', 'Tax_Rate', 'Total_Equity', 'Total_Assets',
        'Current_Assets', 'Current_Liabilities'
    ]
    
    for c in expected_cols:
        if c not in df.columns: df[c] = 0
            
    for col in df.columns:
        if df[col].dtype == 'object': 
            try:
                df[col] = df[col].astype(str).str.replace(',', '').replace('-', '0')
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            except:
                pass 
        elif pd.api.types.is_numeric_dtype(df[col]):
             df[col] = df[col].fillna(0)

    if df['Change_in_WC'].sum() == 0:
        if df['Current_Assets'].sum() != 0 and df['Current_Liabilities'].sum() != 0:
            df['Calculated_WC'] = df['Current_Assets'] - df['Current_Liabilities']
            df['Change_in_WC'] = df['Calculated_WC'].diff().fillna(0)

    df['EBIT'] = df['EBITDA'] - df['Depreciation']
    df['NOPAT'] = df['EBIT'] * (1 - df['Tax_Rate'])
    df['FCFF'] = df['NOPAT'] + df['Depreciation'] - df['CapEx'] - df['Change_in_WC']
    
    df['ROE'] = np.where(df['Total_Equity'] != 0, df['Net_Income'] / df['Total_Equity'], 0)
    df['PE'] = np.where(df['Net_Income'] != 0, df['Avg_Price'] / (df['Net_Income'] / df['Shares_Outstanding']), 0)
    
    market_cap = df['Avg_Price'] * df['Shares_Outstanding']
    df['Enterprise_Value'] = market_cap + df['Total_Debt'] - df['Cash_Equivalents']
    df['EV_EBITDA'] = np.where(df['EBITDA'] != 0, df['Enterprise_Value'] / df['EBITDA'], 0)
    df['PB_Ratio'] = np.where(df['Total_Equity'] != 0, market_cap / df['Total_Equity'], 0)

    return df

# --- 4. DYNAMIC CALCULATION ENGINE ---
def calculate_wacc_dynamic(row):
    rf = row['Risk_Free_Rate']
    rm = row['Market_Return']
    beta = row['Beta']
    
    if rf == 0 and rm == 0:
        ke = 0.12
    else:
        ke = rf + beta * (rm - rf)
    
    debt = row['Total_Debt']
    interest = row['Interest_Expense']
    tax_rate = row['Tax_Rate']
    
    if debt > 0:
        kd_pre_tax = interest / debt
        if kd_pre_tax > MAX_KD_PRE_TAX or kd_pre_tax < MIN_KD_PRE_TAX: 
            kd_pre_tax = DEFAULT_KD_PRE_TAX 
    else:
        kd_pre_tax = 0.0
        
    kd = kd_pre_tax * (1 - tax_rate)
    
    market_cap = row['Avg_Price'] * row['Shares_Outstanding']
    total_val = market_cap + debt
    
    we = market_cap / total_val if total_val > 0 else 1
    wd = debt / total_val if total_val > 0 else 0
    
    wacc = (we * ke) + (wd * kd)
    
    if wacc < 0.03: wacc = 0.03
        
    return wacc, ke, kd

def project_financials(latest, wacc, growth_rate, tg, years=10):
    rev_base = latest['Revenue']
    tax_rate = latest['Tax_Rate']
    
    constant_ebit_margin = latest['EBIT'] / rev_base if rev_base > 0 else 0
    dep_pct = latest['Depreciation'] / rev_base if rev_base > 0 else 0
    capex_pct = latest['CapEx'] / rev_base if rev_base > 0 else 0
    wc_pct = latest['Change_in_WC'] / rev_base if rev_base > 0 else 0
    
    projections = []
    future_fcff = []
    current_growth = growth_rate
    
    for i in range(1, years + 1):
        if i > 5:
            fade = max(growth_rate - tg, 0) / 5
            current_growth = current_growth - fade
            
        if i == 1:
            p_rev = rev_base * (1 + current_growth)
        else:
            p_rev = projections[-1]['Revenue'] * (1 + current_growth)
        
        p_ebit = p_rev * constant_ebit_margin
        p_nopat = p_ebit * (1 - tax_rate)
        p_dep = p_rev * dep_pct
        p_capex = p_rev * capex_pct
        p_wc = p_rev * wc_pct
        p_fcff = p_nopat + p_dep - p_capex - p_wc
        
        if wacc == 0: wacc = 0.1
        
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
        
    last_fcff = future_fcff[-1]
    rf = latest['Risk_Free_Rate'] if latest['Risk_Free_Rate'] > 0 else 0.05
    safe_tg = min(tg, rf, MACRO_GROWTH_CEILING)
    
    if wacc <= safe_tg + TG_BUFFER:
        safe_tg = wacc - TG_BUFFER
    
    tv = (last_fcff * (1 + safe_tg)) / (wacc - safe_tg)
    pv_tv = tv / ((1 + wacc) ** years)
    
    return pd.DataFrame(projections), pv_tv, tv

def calculate_valuation(latest, proj_df, pv_tv):
    enterprise_val = proj_df['PV FCFF'].sum() + pv_tv
    equity_val = enterprise_val - latest['Total_Debt'] + latest['Cash_Equivalents']
    target_price = equity_val / latest['Shares_Outstanding']
    target_price = max(target_price, 0)
    return target_price, equity_val

def format_chart(fig):
    fig.update_layout(
        font=dict(color="#1e293b", family="Inter, sans-serif"),
        title=dict(font=dict(color="#1e293b", size=18)),
        legend=dict(font=dict(color="#1e293b")),
        xaxis=dict(title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b"), showgrid=False),
        yaxis=dict(title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b"), showgrid=True, gridcolor='#f1f5f9'),
        plot_bgcolor='white',
        paper_bgcolor='white',
        margin=dict(l=40, r=40, t=60, b=40)
    )
    return fig

# --- 5. REPORTING ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'SENTINEL - Institutional Valuation Report', 0, 1, 'R')
        self.line(10, 20, 200, 20)
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()} | Generated by Sentinel Financial Analytics', 0, 0, 'C')

def generate_pdf(ticker, target, upside, wacc, ke, kd, tg, proj_df, latest_data, peer_df, hist_df, risks, cca_val_pe=None, cca_val_ev=None):
    pdf = PDFReport()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"Equity Research Report: {ticker}", 0, 1)
    pdf.set_font("Arial", '', 10)
    pdf.cell(0, 10, f"Valuation Date: {datetime.now().strftime('%Y-%m-%d')}", 0, 1)
    pdf.ln(5)
    
    rec = "BUY" if upside > 15 else "ACCUMULATE" if upside > 0 else "HOLD" if upside > -10 else "SELL"
    color = (0, 128, 0) if upside > 0 else (200, 0, 0)
    
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(*color)
    pdf.cell(0, 10, f"Recommendation: {rec} ({upside:+.1f}%)", 0, 1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)
    
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
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. Methodology & Formulas", 0, 1)
    pdf.set_font("Arial", '', 10)
    formula_text = (
        "We utilize the Weighted Average Cost of Capital (WACC) to discount future Free Cash Flows to Firm (FCFF).\n\n"
        "FORMULAS USED:\n"
        "A) WACC = (We * Ke) + (Wd * Kd)\n"
        "B) FCFF = NOPAT + Depreciation - CapEx - Change in Working Capital\n"
        "C) Terminal Value = (Final FCFF * (1 + Terminal Growth)) / (WACC - Terminal Growth)"
    )
    pdf.multi_cell(0, 6, formula_text)
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "2. WACC Calculation (Inputs from Data)", 0, 1)
    pdf.set_font("Arial", '', 10)
    
    wacc_data = [
        ("Risk Free Rate (Rf)", f"{latest_data['Risk_Free_Rate']*100:.2f}%"),
        ("Market Return (Rm)", f"{latest_data['Market_Return']*100:.2f}%"),
        ("Beta", f"{latest_data['Beta']:.2f}"),
        ("Cost of Equity (Ke)", f"{ke*100:.2f}%"),
        ("Cost of Debt (Pre-tax)", f"{kd/(1-latest_data['Tax_Rate'])*100:.2f}%"),
        ("Tax Rate", f"{latest_data['Tax_Rate']*100:.1f}%"),
        ("Final WACC", f"{wacc*100:.2f}%")
    ]
    
    pdf.set_fill_color(240, 240, 240)
    for i, (metric, val) in enumerate(wacc_data):
        fill = 1 if i % 2 == 0 else 0
        pdf.cell(80, 8, metric, 1, 0, 'L', fill)
        pdf.cell(40, 8, val, 1, 1, 'C', fill)
    pdf.ln(5)
    
    pdf.add_page()
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "3. 5-Year Cash Flow Projections (Forecast)", 0, 1)
    
    pdf.set_font("Arial", 'B', 9)
    pdf.set_fill_color(50, 50, 50)
    pdf.set_text_color(255, 255, 255)
    headers = ["Year", "Revenue", "EBIT", "NOPAT", "CapEx", "FCFF", "PV of FCFF"]
    col_widths = [15, 30, 30, 30, 30, 30, 30]
    
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 10, h, 1, 0, 'C', 1)
    pdf.ln()
    
    pdf.set_font("Arial", '', 9)
    pdf.set_text_color(0, 0, 0)
    
    for index, row in proj_df.head(5).iterrows():
        pdf.cell(col_widths[0], 10, str(row['Year']), 1, 0, 'C')
        pdf.cell(col_widths[1], 10, f"{row['Revenue']:,.0f}", 1, 0, 'R')
        pdf.cell(col_widths[2], 10, f"{row['EBIT']:,.0f}", 1, 0, 'R')
        pdf.cell(col_widths[3], 10, f"{row['NOPAT']:,.0f}", 1, 0, 'R')
        pdf.cell(col_widths[4], 10, f"{row['CapEx']:,.0f}", 1, 0, 'R')
        pdf.cell(col_widths[5], 10, f"{row['FCFF']:,.0f}", 1, 0, 'R')
        pdf.cell(col_widths[6], 10, f"{row['PV FCFF']:,.0f}", 1, 1, 'R')
    pdf.ln(5)
    
    if cca_val_pe is not None and cca_val_ev is not None:
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "4. Relative Valuation (Implied)", 0, 1)
        pdf.set_font("Arial", '', 10)
        cca_text = (
            f"Based on peer median multiples:\n"
            f"- Implied Price (P/E): INR {cca_val_pe:,.2f}\n"
            f"- Implied Price (EV/EBITDA): INR {cca_val_ev:,.2f}"
        )
        pdf.multi_cell(0, 6, cca_text)
        pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "5. Key Risks", 0, 1)
    pdf.set_font("Arial", '', 10)
    for r in risks:
        pdf.multi_cell(0, 6, f"- {r}")
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 6. MAIN APPLICATION ---
def main():
    if not st.session_state.get('authenticated', False):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c2:
            st.markdown("""
            <div class="login-container">
                <div class="login-title">Sentinel</div>
                <div class="login-subtitle">Institutional Financial Intelligence</div>
            """, unsafe_allow_html=True)
            
            user = st.text_input("Username", placeholder="admin")
            pw = st.text_input("Password", type="password", placeholder="••••••••")
            
            if st.button("Access Dashboard", use_container_width=True):
                if user=="admin" and pw=="password123":
                    st.session_state['authenticated'] = True
                    st.session_state['user'] = "admin"
                    st.rerun()
                else:
                    st.error("Access Denied")
            st.markdown("</div>", unsafe_allow_html=True)
        return

    # Sidebar
    st.sidebar.markdown("""
        <div style='text-align: center; padding: 30px 0;'>
            <h1 style='color: white; margin:0; font-size: 28px; letter-spacing:1px; font-family:"Playfair Display"'>SENTINEL</h1>
            <p style='color: #94a3b8; font-size: 11px; margin-top:5px; text-transform:uppercase; letter-spacing:2px;'>Analytics Suite v5.0</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.sidebar.markdown(f"**Analyst:** {st.session_state['user']}")
    if st.sidebar.button("Log Out"):
        st.session_state['authenticated'] = False
        st.session_state['user'] = None
        st.rerun()
        
    st.sidebar.markdown("---")
    st.sidebar.subheader("Data Management")
    
    # Template Download
    template_file = generate_excel_template()
    st.sidebar.download_button(
        label="📥 Download Excel Template",
        data=template_file,
        file_name="sentinel_data_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Download a pre-formatted Excel file with required columns."
    )
    
    uploaded_file = st.sidebar.file_uploader("Upload Data Model (XLSX)", type=['xlsx'])
    
    if uploaded_file:
        raw_data, sheets = load_data(uploaded_file)
        if not raw_data: return
        
        st.sidebar.subheader("Analysis Controls")
        ticker = st.sidebar.selectbox("Select Company", sheets)
        
        with st.sidebar.expander("Modify Key Inputs", expanded=False):
            try:
                base_rev_growth = float(raw_data[ticker].iloc[-1]['Projected_Growth'])
                base_term_growth = float(raw_data[ticker].iloc[-1]['Terminal_Growth'])
            except:
                base_rev_growth = 0.10
                base_term_growth = 0.04
            
            user_proj_growth = st.slider(f"Revenue Growth (Base: {base_rev_growth:.1%})", 0.0, 0.20, base_rev_growth, 0.005)
            user_term_growth = st.slider(f"Terminal Growth (Base: {base_term_growth:.1%})", 0.0, 0.10, base_term_growth, 0.005)
            user_wacc_adj = st.slider("WACC Adjustment", -0.02, 0.02, 0.0, 0.001)
        
        df = process_data(raw_data[ticker].copy())
        if df.empty:
            st.error("Data processing failed.")
            return

        latest = df.iloc[-1]
        risks = [
            "Macroeconomic headwinds affecting consumer discretionary spending.",
            "Raw material price volatility impacting gross margins.",
            "Competitive intensity from new D2C entrants.",
            "Regulatory risks regarding environmental standards.",
            "Execution risks in new market expansion."
        ]
        
        base_wacc, ke, kd = calculate_wacc_dynamic(latest)
        final_wacc = max(base_wacc + user_wacc_adj, 0.03)
        
        scenarios = {
            "Base Case": (user_proj_growth, user_term_growth),
            "Bull Case": (user_proj_growth * 1.2, user_term_growth * 1.1),
            "Bear Case": (user_proj_growth * 0.8, user_term_growth * 0.9)
        }
        selected_scenario = st.sidebar.selectbox("Select Scenario", list(scenarios.keys()))
        s_pg, s_tg = scenarios[selected_scenario]
        
        proj_df, pv_tv, tv_val = project_financials(latest, final_wacc, s_pg, s_tg, years=10) 
        target_price, equity_val = calculate_valuation(latest, proj_df, pv_tv)
        
        if equity_val < 0:
            risks.append("HIGH RISK: Implied Equity Value is negative due to high debt.")
        
        # Live Price Fetch
        live_price = latest['Avg_Price']
        is_live = False
        TICKER_MAP = {
            'HUL': 'HINDUNILVR.NS', 'ITC': 'ITC.NS', 'COLPAL': 'COLPAL.NS', 
            'NESTLE': 'NESTLEIND.NS', 'BRITANNIA': 'BRITANNIA.NS'
        }
        y_ticker = TICKER_MAP.get(ticker.upper(), f"{ticker}.NS")
        
        try:
            stock = yf.Ticker(y_ticker)
            hist = stock.history(period="5d")
            if not hist.empty:
                live_price = hist['Close'].iloc[-1]
                is_live = True
        except: pass
            
        upside = (target_price - live_price)/live_price * 100
        
        # --- DASHBOARD CONTENT ---
        st.markdown(f"## {ticker} Valuation Analysis")
        st.markdown(f"**Date:** {datetime.now().strftime('%d %B %Y')} &nbsp;|&nbsp; **Currency:** INR Crores &nbsp;|&nbsp; **Scenario:** {selected_scenario}")
        
        if is_live:
            st.markdown(f'<div class="live-badge"><div class="live-dot"></div> Live Market Data Active ({y_ticker})</div>', unsafe_allow_html=True)
        else:
            st.warning("Using Book Price (Live data unavailable)")
            
        st.markdown("### Executive Summary")
        c1, c2, c3, c4 = st.columns(4)
        
        with c1: st.markdown(f'<div class="metric-card"><div class="metric-lbl">Intrinsic Value</div><div class="metric-val">₹{target_price:,.0f}</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="metric-card"><div class="metric-lbl">Current Price</div><div class="metric-val">₹{live_price:,.0f}</div></div>', unsafe_allow_html=True)
        
        up_color = "var(--success-color)" if upside > 0 else "#ef4444"
        with c3: st.markdown(f'<div class="metric-card" style="border-bottom: 4px solid {up_color}"><div class="metric-lbl">Upside</div><div class="metric-val" style="color:{up_color} !important">{upside:+.1f}%</div></div>', unsafe_allow_html=True)
        with c4: st.markdown(f'<div class="metric-card"><div class="metric-lbl">WACC</div><div class="metric-val">{final_wacc:.1%}</div></div>', unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        t1, t2, t3, t4, t5 = st.tabs(["Projections", "WACC Build", "Sensitivity", "Comps", "Report"])
        
        with t1:
            st.markdown("#### 5-Year Cash Flow Forecast")
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            st.dataframe(proj_df.head(5).style.format("{:,.0f}").background_gradient(subset=['FCFF'], cmap='Greens'), use_container_width=True)
            
            fig_proj = go.Figure()
            fig_proj.add_trace(go.Bar(x=proj_df['Year'], y=proj_df['Revenue'], name='Revenue', marker_color='#cbd5e1'))
            fig_proj.add_trace(go.Scatter(x=proj_df['Year'], y=proj_df['FCFF'], name='FCFF', line=dict(color='#2c3e50', width=3), yaxis='y2'))
            fig_proj.update_layout(title="Revenue vs Free Cash Flow", yaxis2=dict(overlaying='y', side='right', showgrid=False))
            st.plotly_chart(format_chart(fig_proj), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with t2:
            st.markdown("#### Cost of Capital Decomposition")
            c_w1, c_w2 = st.columns(2)
            with c_w1:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                st.markdown("**Cost of Equity (Ke)**")
                st.table(pd.DataFrame({
                    "Metric": ["Risk Free Rate", "Beta", "Market Return", "Ke"],
                    "Value": [f"{latest['Risk_Free_Rate']:.2%}", f"{latest['Beta']:.2f}", f"{latest['Market_Return']:.2%}", f"{ke:.2%}"]
                }))
                st.markdown('</div>', unsafe_allow_html=True)
            with c_w2:
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                st.markdown("**WACC Components**")
                st.table(pd.DataFrame({
                    "Metric": ["Cost of Debt (Post-Tax)", "Tax Rate", "Debt Weight", "Equity Weight", "WACC"],
                    "Value": [f"{kd:.2%}", f"{latest['Tax_Rate']:.1%}", f"{latest['Total_Debt']/(latest['Total_Debt'] + (latest['Avg_Price']*latest['Shares_Outstanding'])):.1%}", f"{(latest['Avg_Price']*latest['Shares_Outstanding'])/(latest['Total_Debt'] + (latest['Avg_Price']*latest['Shares_Outstanding'])):.1%}", f"{final_wacc:.2%}"]
                }))
                st.markdown('</div>', unsafe_allow_html=True)

        with t3:
            st.markdown("#### Valuation Sensitivity")
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            wacc_range = np.linspace(final_wacc - 0.01, final_wacc + 0.01, 5)
            tg_range = np.linspace(s_tg - 0.005, s_tg + 0.005, 5)
            
            z_values = []
            for w in wacc_range:
                row_z = []
                for t in tg_range:
                    if w <= t + TG_BUFFER: row_z.append(np.nan)
                    else:
                        p_df, p_tv, _ = project_financials(latest, w, s_pg, t, years=10)
                        val, _ = calculate_valuation(latest, p_df, p_tv)
                        row_z.append(val)
                z_values.append(row_z)
                
            fig_heat = go.Figure(data=go.Heatmap(z=z_values, x=[f"{t:.1%}" for t in tg_range], y=[f"{w:.1%}" for w in wacc_range], colorscale='RdBu', texttemplate="₹%{z:.0f}"))
            fig_heat.update_layout(title="Target Price Sensitivity", xaxis_title="Terminal Growth", yaxis_title="WACC", yaxis=dict(autorange="reversed"))
            st.plotly_chart(format_chart(fig_heat), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with t4:
            st.markdown("#### Peer Comparison")
            peers = []
            for t in sheets:
                d = process_data(raw_data[t].copy()).iloc[-1]
                peers.append({
                    'Ticker': t, 'P/E': d['PE'], 'EV/EBITDA': d['EV_EBITDA'],
                    'ROE': d['ROE']*100, 'Rev (Cr)': d['Revenue']
                })
            peer_df = pd.DataFrame(peers).set_index('Ticker')
            
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            st.dataframe(peer_df.style.format("{:.1f}").background_gradient(cmap="Blues"), use_container_width=True)
            
            col_v1, col_v2 = st.columns(2)
            with col_v1:
                fig_scat = px.scatter(peer_df, x='ROE', y='P/E', size='Rev (Cr)', text=peer_df.index, title="P/E vs ROE", color=peer_df.index)
                st.plotly_chart(format_chart(fig_scat), use_container_width=True)
            with col_v2:
                fig_bar = px.bar(peer_df, x=peer_df.index, y='EV/EBITDA', title="EV/EBITDA Multiples", color=peer_df.index)
                st.plotly_chart(format_chart(fig_bar), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with t5:
            st.markdown("#### Investment Memo")
            st.markdown('<div class="content-card" style="text-align:center;">', unsafe_allow_html=True)
            st.markdown("Generate a professional-grade PDF report including all models, charts, and risk assessments.")
            
            pdf_imp_pe, pdf_imp_ev = None, None
            if not peer_df.empty:
                vp = peer_df[peer_df.index != ticker]
                if not vp.empty:
                    pdf_imp_pe = vp['P/E'].median() * (latest['Net_Income'] / latest['Shares_Outstanding'])
                    i_ev = vp['EV/EBITDA'].median() * latest['EBITDA']
                    pdf_imp_ev = (i_ev - (latest['Total_Debt'] - latest['Cash_Equivalents'])) / latest['Shares_Outstanding']

            if st.button("Generate & Download Report", type="primary"):
                pdf_bytes = generate_pdf(ticker, target_price, upside, final_wacc, ke, kd, s_tg, proj_df, latest, peer_df, df, risks, pdf_imp_pe, pdf_imp_ev)
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/pdf;base64,{b64}" download="{ticker}_Report.pdf" style="text-decoration:none; color:white; background-color:#2c3e50; padding:12px 24px; border-radius:8px; font-weight:bold;">Click to Save PDF</a>'
                st.markdown(href, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    else:
        st.info("👋 Welcome to Sentinel. Use the sidebar to upload your financial model or download the template.")

if __name__ == "__main__":
    main()
