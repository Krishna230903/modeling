import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
from datetime import datetime
import yfinance as yf

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
    page_icon="🏛️",
    initial_sidebar_state="expanded"
)

# --- 2. PREMIUM CORPORATE CSS (Strict Black Text Enforcement) ---
st.markdown("""
<style>
    /* Global Typography - Enforce Black & Professional Font */
    html, body, [class*="css"] {
        font-family: 'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #000000 !important; 
    }
    
    /* Main Background - Very Light Cool Grey */
    .stApp {
        background-color: #f4f6f8; 
    }
    
    /* Sidebar Styling - Deep Slate Blue */
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
        border-left: 5px solid #2980b9;
        padding: 20px;
        border-radius: 4px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        transition: transform 0.2s;
        border: 1px solid #e0e0e0;
        margin-bottom: 10px;
        height: 100%; /* Fill column */
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .metric-val {
        font-size: 28px;
        font-weight: 700;
        color: #000000 !important; /* STRICT BLACK */
        margin: 5px 0;
        font-family: 'Roboto Mono', monospace; 
    }
    .metric-lbl {
        font-size: 12px;
        color: #000000 !important; /* STRICT BLACK */
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 700;
    }
    
    /* Custom Content Cards */
    .content-card {
        background-color: #ffffff;
        padding: 25px;
        border-radius: 4px;
        border: 1px solid #d1d5db;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    
    /* Login Page Styling */
    .login-container {
        background-color: #ffffff;
        padding: 50px;
        border-radius: 8px;
        box-shadow: 0 20px 50px rgba(0,0,0,0.1);
        text-align: center;
        max-width: 450px;
        margin: 100px auto;
        border-top: 6px solid #2c3e50;
    }
    .login-header {
        font-family: 'Playfair Display', serif;
        font-size: 32px;
        font-weight: 700;
        color: #000000 !important; /* STRICT BLACK */
        margin-bottom: 10px;
    }
    .login-sub {
        color: #000000 !important; /* STRICT BLACK */
        font-size: 14px;
        margin-bottom: 30px;
        font-weight: 500;
    }
    .login-label {
        text-align: left;
        font-weight: 700;
        font-size: 14px;
        margin-bottom: 5px;
        color: #000000 !important; /* STRICT BLACK */
    }
    
    /* Tables */
    thead tr th {
        background-color: #e9ecef !important;
        color: #000000 !important;
        font-weight: 800 !important;
        border-bottom: 2px solid #bdc3c7 !important;
        font-family: 'Inter', sans-serif;
    }
    tbody tr:nth-child(even) {
        background-color: #f8f9fa;
    }
    tbody tr td {
        color: #000000 !important;
        font-weight: 600;
        font-family: 'Roboto Mono', monospace; 
        font-size: 14px;
    }
    
    /* Live Data Badge */
    .live-badge {
        display: inline-block;
        padding: 6px 12px;
        background-color: #e8f5e9;
        color: #2e7d32 !important;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 700;
        border: 1px solid #a5d6a7;
        margin-left: 10px;
        vertical-align: middle;
    }
    
    /* Headers */
    h1, h2, h3, h4 {
        color: #000000 !important;
        font-weight: 800;
        letter-spacing: -0.5px;
        font-family: 'Playfair Display', serif; 
    }
    
    /* Buttons */
    .stButton button {
        background-color: #2c3e50;
        color: white;
        font-weight: 600;
        border-radius: 4px;
        border: none;
        padding: 0.5rem 1rem;
    }
    .stButton button:hover {
        background-color: #34495e;
        color: white;
    }
    
    /* Input Labels */
    div[data-testid="stMarkdownContainer"] p {
        color: #000000 !important;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. DATA ENGINE ---
@st.cache_data(show_spinner=False)
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
    # Added Current_Assets and Current_Liabilities to calculate WC if Change_in_WC is missing
    expected_cols = [
        'Revenue', 'EBITDA', 'Net_Income', 'Depreciation', 'Interest_Expense',
        'CapEx', 'Change_in_WC', 'Total_Debt', 'Cash_Equivalents', 'Shares_Outstanding',
        'Avg_Price', 'Beta', 'Risk_Free_Rate', 'Market_Return', 'Terminal_Growth', 
        'Projected_Growth', 'Tax_Rate', 'Total_Equity', 'Total_Assets',
        'Current_Assets', 'Current_Liabilities'
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

    # 2.1 Calculate Change in WC if it is zero
    # Logic: WC = Current Assets - Current Liabilities. Change = WC_this_year - WC_last_year
    if df['Change_in_WC'].sum() == 0:
        # Check if we have data to calculate it
        if df['Current_Assets'].sum() != 0 and df['Current_Liabilities'].sum() != 0:
            df['Calculated_WC'] = df['Current_Assets'] - df['Current_Liabilities']
            df['Change_in_WC'] = df['Calculated_WC'].diff().fillna(0)

    # 3. Calculate Base Metrics (FCFF)
    df['EBIT'] = df['EBITDA'] - df['Depreciation']
    df['NOPAT'] = df['EBIT'] * (1 - df['Tax_Rate'])
    
    # Exact FCFF Formula: NOPAT + D&A - CapEx - Change in Working Capital
    # Convention: Change_in_WC is (Current Year WC - Previous Year WC). Positive means cash outflow.
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
    
    # Fallback if Rf or Rm are 0 (prevents WACC=0 and Discount Factor=1)
    if rf == 0 and rm == 0:
        # Default logic if data is missing to prevent math errors
        ke = 0.12 # 12% default Cost of Equity
    else:
        ke = rf + beta * (rm - rf)
    
    # 2. Cost of Debt (Kd)
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
    
    # 3. Weights
    market_cap = row['Avg_Price'] * row['Shares_Outstanding']
    total_val = market_cap + debt
    
    we = market_cap / total_val if total_val > 0 else 1
    wd = debt / total_val if total_val > 0 else 0
    
    wacc = (we * ke) + (wd * kd)
    
    # Safety: Hard Floor for WACC to prevent mathematical explosions or invalid economics
    # Minimum 3% WACC
    if wacc < 0.03:
        wacc = 0.03
        
    return wacc, ke, kd

def project_financials(latest, wacc, growth_rate, tg, years=10):
    """
    Projects financials 10 years out (standard for quality FMCG).
    Uses 'Projected_Growth' passed as argument.
    """
    rev_base = latest['Revenue']
    tax_rate = latest['Tax_Rate']
    
    # Ratios as % of Revenue
    # Assumption: Constant margins going forward (no operating leverage modeled)
    constant_ebit_margin = latest['EBIT'] / rev_base if rev_base > 0 else 0
    dep_pct = latest['Depreciation'] / rev_base if rev_base > 0 else 0
    # Assumption: Linear reinvestment rates
    capex_pct = latest['CapEx'] / rev_base if rev_base > 0 else 0
    wc_pct = latest['Change_in_WC'] / rev_base if rev_base > 0 else 0
    
    projections = []
    future_fcff = []
    
    current_growth = growth_rate
    
    for i in range(1, years + 1):
        # Linearly fade growth after year 5 towards terminal growth
        if i > 5:
            # Bug Fix: Ensure fade doesn't increase growth if growth_rate < tg
            fade = max(growth_rate - tg, 0) / 5
            current_growth = current_growth - fade
            
        # 1. Grow Revenue
        if i == 1:
            p_rev = rev_base * (1 + current_growth)
        else:
            p_rev = projections[-1]['Revenue'] * (1 + current_growth)
        
        # 2. Apply Margins
        p_ebit = p_rev * constant_ebit_margin
        p_nopat = p_ebit * (1 - tax_rate)
        p_dep = p_rev * dep_pct
        p_capex = p_rev * capex_pct
        p_wc = p_rev * wc_pct
        
        # 3. Calculate FCFF
        p_fcff = p_nopat + p_dep - p_capex - p_wc
        
        # 4. Discount to PV
        # Ensure wacc isn't 0
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
        
    # Terminal Value (Gordon Growth Method)
    last_fcff = future_fcff[-1]
    
    # --- RIGOROUS ECONOMICS SAFETY CHECK ---
    # 1. Cap TG at Risk Free Rate (Standard Practice)
    # 2. Cap TG at 5% (Macro Ceiling)
    # 3. Cap TG at WACC - Buffer (Mathematical Necessity)
    
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
    
    # Valuation Safety: Equity Value cannot effectively be negative for target price context (limited liability)
    # Though mathematically DCF can be negative, standard output often floors at 0 or flags it.
    target_price = equity_val / latest['Shares_Outstanding']
    target_price = max(target_price, 0)
    
    return target_price, equity_val

# Helper to enforce black text on charts
def format_chart(fig):
    fig.update_layout(
        font=dict(color="black", family="Inter, sans-serif"),
        title=dict(font=dict(color="black")),
        legend=dict(font=dict(color="black")),
        xaxis=dict(
            title_font=dict(color="black"),
            tickfont=dict(color="black"),
            showgrid=False
        ),
        yaxis=dict(
            title_font=dict(color="black"),
            tickfont=dict(color="black"),
            showgrid=False
        ),
        plot_bgcolor='white',
        paper_bgcolor='white'
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
    
    # Methodology & Formulas (NEW SECTION)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. Methodology & Formulas", 0, 1)
    pdf.set_font("Arial", '', 10)
    formula_text = (
        "We utilize the Weighted Average Cost of Capital (WACC) to discount future Free Cash Flows to Firm (FCFF).\n\n"
        "FORMULAS USED:\n"
        "A) WACC = (We * Ke) + (Wd * Kd)  [Where Kd is post-tax cost of debt]\n"
        "   - We/Wd: Weights of Equity and Debt\n"
        "   - Ke: Cost of Equity (CAPM) = Risk Free Rate + Beta * (Market Return - Risk Free Rate)\n"
        "   - Kd: Cost of Debt (Post-Tax) = (Interest Expense / Total Debt) * (1 - Tax Rate)\n\n"
        "B) FCFF = NOPAT + Depreciation - CapEx - Change in Working Capital\n"
        "   - NOPAT: Net Operating Profit After Tax = EBIT * (1 - Tax Rate)\n\n"
        "C) Terminal Value = (Final FCFF * (1 + Terminal Growth)) / (WACC - Terminal Growth)"
    )
    pdf.multi_cell(0, 6, formula_text)
    pdf.ln(5)

    # Detailed WACC Calculation
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "2. WACC Calculation (Inputs from Data)", 0, 1)
    pdf.set_font("Arial", '', 10)
    
    # Create a simple table layout for WACC components
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
    
    # 5-Year Projections Table (Explicit Request)
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
    
    # Comparable Analysis
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "4. Comparable Company Analysis (CCA)", 0, 1)
    
    pdf.set_font("Arial", 'B', 9)
    pdf.set_fill_color(50, 50, 50)
    pdf.set_text_color(255, 255, 255)
    cols = ["Ticker", "P/E Ratio", "EV/EBITDA", "ROE (%)", "Revenue (Cr)"]
    widths = [30, 30, 35, 30, 40]
    
    for i, c in enumerate(cols):
        pdf.cell(widths[i], 10, c, 1, 0, 'C', 1)
    pdf.ln()
    
    pdf.set_font("Arial", '', 9)
    pdf.set_text_color(0, 0, 0)
    for index, row in peer_df.iterrows():
        pdf.cell(widths[0], 10, str(index), 1, 0, 'C')
        pdf.cell(widths[1], 10, f"{row['P/E Ratio']:.1f}x", 1, 0, 'C')
        pdf.cell(widths[2], 10, f"{row['EV/EBITDA']:.1f}x", 1, 0, 'C')
        pdf.cell(widths[3], 10, f"{row['ROE (%)']:.1f}%", 1, 0, 'C')
        pdf.cell(widths[4], 10, f"{row['Revenue (Cr)']:,.0f}", 1, 1, 'C')
    pdf.ln(5)

    # CCA Valuation Implied Prices (New Section)
    if cca_val_pe is not None and cca_val_ev is not None:
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Relative Valuation (Implied Intrinsic Value)", 0, 1)
        pdf.set_font("Arial", '', 10)
        
        cca_text = (
            f"Based on the median multiples of the peer group (excluding {ticker}), we derive the following implied values:\n"
            f"- Implied Price (P/E Basis): INR {cca_val_pe:,.2f} per share\n"
            f"- Implied Price (EV/EBITDA Basis): INR {cca_val_ev:,.2f} per share"
        )
        pdf.multi_cell(0, 6, cca_text)
        pdf.ln(5)
    
    # Historical Data Table
    pdf.add_page()
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "5. Historical Financial Data (Uploaded)", 0, 1)
    
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
    
    # Risks Section (New)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "6. Key Risks & Assumptions", 0, 1)
    pdf.set_font("Arial", '', 10)
    for r in risks:
        pdf.multi_cell(0, 6, f"- {r}")
        
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
                <div class="login-header">SENTINEL</div>
                <div class="login-sub">Institutional Financial Intelligence</div>
                <div class="login-label">Secure Access</div>
            """, unsafe_allow_html=True)
            
            user = st.text_input("Username", placeholder="admin")
            pw = st.text_input("Password", type="password", placeholder="••••••••")
            
            if st.button("Secure Login", use_container_width=True):
                if user=="admin" and pw=="password123":
                    st.session_state['authenticated'] = True
                    st.session_state['user'] = "admin"
                    st.rerun()
                else:
                    st.error("Access Denied: Invalid Credentials")
            
            st.markdown("</div>", unsafe_allow_html=True)
        return

    # Sidebar Layout
    st.sidebar.markdown("""<div style='text-align: center; padding: 20px 0;'><h2 style='color: white; margin:0; letter-spacing:1px;'>SENTINEL</h2><p style='color: #bdc3c7; font-size: 11px; margin-top:5px;'>ANALYTICS SUITE v5.0</p></div>""", unsafe_allow_html=True)
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
        
        # Explicit Assumptions Panel
        st.sidebar.markdown("### ⚙️ Assumptions Overrides")
        with st.sidebar.expander("Modify Key Inputs", expanded=False):
            # Display current base values for context
            base_rev_growth = float(raw_data[ticker].iloc[-1]['Projected_Growth'])
            base_term_growth = float(raw_data[ticker].iloc[-1]['Terminal_Growth'])
            
            user_proj_growth = st.slider(f"Revenue Growth (Base: {base_rev_growth:.1%})", 0.0, 0.20, base_rev_growth, 0.005)
            user_term_growth = st.slider(f"Terminal Growth (Base: {base_term_growth:.1%})", 0.0, 0.10, base_term_growth, 0.005)
            user_wacc_adj = st.slider("WACC Adjustment (Base: 0.0%)", -0.02, 0.02, 0.0, 0.001)
        
        # 1. READ & PROCESS DATA
        df = process_data(raw_data[ticker].copy())
        latest = df.iloc[-1]
        
        # Define Risks List Early for accumulation
        risks = [
            "Macroeconomic headwinds affecting consumer discretionary spending.",
            "Fluctuations in raw material prices (commodities) impacting margins.",
            "Intensifying competitive landscape from new entrants and D2C brands.",
            "Regulatory changes in taxation or environmental standards.",
            "Execution risk in new product launches or market expansion.",
            "Linear fade approximation used for growth rates converging to terminal growth."
        ]
        
        # 2. DYNAMIC CALCULATION
        base_wacc, ke, kd = calculate_wacc_dynamic(latest)
        
        # WACC Guardrail: Prevent negative or dangerously low WACC
        # Ensuring Final WACC is at least 3% strictly
        final_wacc = max(base_wacc + user_wacc_adj, 0.03)
        
        if final_wacc != (base_wacc + user_wacc_adj):
            st.toast("⚠️ WACC adjusted to minimum floor of 3.0%", icon="🛡️")

        # Display warning if WACC was defaulted
        if latest['Risk_Free_Rate'] == 0:
            st.toast("⚠️ Warning: Risk Free Rate is 0 in data. Used default WACC.", icon="⚠️")
        
        # Scenario Analysis
        scenarios = {
            "Base Case": (user_proj_growth, user_term_growth),
            "Bull Case": (user_proj_growth * 1.2, user_term_growth * 1.1),
            "Bear Case": (user_proj_growth * 0.8, user_term_growth * 0.9)
        }
        selected_scenario = st.sidebar.selectbox("Select Scenario", list(scenarios.keys()))
        s_pg, s_tg = scenarios[selected_scenario]
        
        # Calculate 10yr for value, but display 5yr focus
        proj_df, pv_tv, tv_val = project_financials(latest, final_wacc, s_pg, s_tg, years=10) 
        target_price, equity_val = calculate_valuation(latest, proj_df, pv_tv)
        
        # Risk Check: Negative Equity Value
        if equity_val < 0:
            risks.append("⚠️ HIGH RISK: Implied Equity Value is negative due to high debt load relative to cash flows.")
            st.error("Warning: High leverage is eroding equity value.")
        
        # 3. LIVE MARKET DATA
        live_price = latest['Avg_Price']
        is_live = False
        y_ticker = None
        # Default mapping, can be extended
        TICKER_MAP = {
            'HUL': 'HINDUNILVR.NS', 
            'ITC': 'ITC.NS', 
            'COLPAL': 'COLPAL.NS', 
            'COLGATE': 'COLPAL.NS',
            'NESTLE': 'NESTLEIND.NS',
            'BRITANNIA': 'BRITANNIA.NS'
        }
        
        # Try mapped ticker, then default to Ticker.NS
        y_ticker = TICKER_MAP.get(ticker.upper(), f"{ticker}.NS")
        
        try:
            stock = yf.Ticker(y_ticker)
            # Try history first as it's often more reliable than fast_info
            hist = stock.history(period="5d")
            if not hist.empty:
                live_price = hist['Close'].iloc[-1]
                is_live = True
            else:
                # Fallback to fast_info
                fast_info = stock.fast_info
                if fast_info and 'last_price' in fast_info and fast_info.last_price:
                    live_price = fast_info.last_price
                    is_live = True
        except Exception as e:
            # Silent fail to book price if live fetch fails
            pass
            
        upside = (target_price - live_price)/live_price * 100
        
        # --- HEADER SECTION ---
        st.title(f"{ticker} Valuation Analysis")
        st.markdown(f"**Valuation Date:** {datetime.now().strftime('%d %B %Y')} | **Financials:** INR Crores | **Share Prices:** INR per share | **Scenario:** {selected_scenario}")
        
        if is_live:
            st.markdown(f'<div class="live-badge">⚡ Live Market Price Active ({y_ticker})</div>', unsafe_allow_html=True)
        else:
            st.warning("Using Book Price (Live data unavailable)")
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # --- KPI CARDS ---
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f'<div class="metric-card"><div class="metric-lbl">Target Value (Intrinsic)</div><div class="metric-val">₹ {target_price:,.2f}</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="metric-card"><div class="metric-lbl">Current Price {"(Live)" if is_live else "(Book)"}</div><div class="metric-val">₹ {live_price:,.2f}</div></div>', unsafe_allow_html=True)
        
        up_color = "#27ae60" if upside > 0 else "#c0392b"
        c3.markdown(f'<div class="metric-card" style="border-left: 5px solid {up_color};"><div class="metric-lbl">Implied Upside</div><div class="metric-val" style="color:{up_color}">{upside:+.2f}%</div></div>', unsafe_allow_html=True)
        
        c4.markdown(f'<div class="metric-card"><div class="metric-lbl">WACC (Applied)</div><div class="metric-val">{final_wacc:.1%}</div></div>', unsafe_allow_html=True)
        
        # Additional Insights Row
        if latest['Net_Income'] > (0.05 * latest['Revenue']): # Threshold for valid P/E
             implied_pe = target_price / (latest['Net_Income']/latest['Shares_Outstanding'])
             pe_display = f"{implied_pe:.1f}x"
        else:
             implied_pe = np.nan
             pe_display = "N/A (Low Earnings)"
             
        terminal_dependency = (pv_tv / (proj_df['PV FCFF'].sum() + pv_tv)) * 100
        
        st.markdown(f"""
        <div style="display:flex; justify-content:space-around; margin-top:10px; background-color:#e0f2f1; padding:10px; border-radius:5px;">
            <div style="color:black;"><strong>Terminal Value Share of EV:</strong> {terminal_dependency:.1f}% {'⚠️' if terminal_dependency > TERMINAL_VALUE_WARNING_THRESHOLD else '✅'}</div>
            <div style="color:black;"><strong>Implied P/E @ Target:</strong> {pe_display}</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # --- TABS ---
        t1, t2, t3, t4, t5 = st.tabs(["📊 Projections (5Y)", "🧮 WACC Build", "📈 Sensitivity", "👥 Comparable Analysis", "📄 Report"])
        
        # Tab 1: Projections
        with t1:
            st.markdown("### Future Cash Flow Projections (Next 5 Years)")
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            # SHOW ONLY FIRST 5 YEARS IN TABLE FOR CLEANLINESS
            # Highlight FCFF and PV FCFF columns using style
            st.dataframe(
                proj_df.head(5).style.format("{:,.0f}")
                .background_gradient(subset=['FCFF', 'PV FCFF'], cmap='Greens'), 
                use_container_width=True
            )
            st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            
            # 1. Multi-line Projection Chart
            fig_proj = go.Figure()
            fig_proj.add_trace(go.Scatter(x=proj_df['Year'], y=proj_df['Revenue'], name='Revenue (Left)', line=dict(color='#2c3e50', width=3), yaxis='y1'))
            fig_proj.add_trace(go.Scatter(x=proj_df['Year'], y=proj_df['EBIT'], name='EBIT', line=dict(color='#2980b9', width=2), yaxis='y2'))
            fig_proj.add_trace(go.Scatter(x=proj_df['Year'], y=proj_df['FCFF'], name='FCFF', line=dict(color='#27ae60', width=2, dash='dot'), yaxis='y2'))
            
            fig_proj.update_layout(
                title="5-Year Financial Forecast (Dual Axis)", 
                yaxis=dict(title='Revenue', showgrid=False),
                yaxis2=dict(title='EBIT / FCFF', overlaying='y', side='right', showgrid=False),
                legend=dict(orientation="h", y=1.1)
            )
            fig_proj = format_chart(fig_proj)
            st.plotly_chart(fig_proj, use_container_width=True)
            
            # 2. Valuation Bridge
            fig = go.Figure(go.Waterfall(
                measure=["relative", "relative", "total"],
                x=["PV Cash Flows (Total)", "PV Terminal Value", "Enterprise Value"],
                y=[proj_df['PV FCFF'].sum(), pv_tv, 0],
                connector={"line":{"color":"#000000"}}
            ))
            fig.update_layout(title="Enterprise Value Composition", height=350)
            fig = format_chart(fig)
            st.plotly_chart(fig, use_container_width=True)
            
            if terminal_dependency > TERMINAL_VALUE_WARNING_THRESHOLD:
                st.warning(f"⚠️ High Terminal Value Dependency: {terminal_dependency:.1f}% of Value comes from perpetuity.")
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
                    "Value": [f"{latest['Interest_Expense']:,.0f}", f"{latest['Total_Debt']:,.0f}", f"{latest['Tax_Rate']:.1%}", f"{kd:.2%}", f"{base_wacc:.2%}"]
                }), hide_index=True, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
        # Tab 3: Sensitivity Analysis
        with t3:
            st.subheader("Sensitivity Analysis")
            
            # Heatmap Data
            wacc_range = np.linspace(final_wacc - 0.01, final_wacc + 0.01, 5)
            tg_range = np.linspace(s_tg - 0.005, s_tg + 0.005, 5)
            
            z_values = []
            for w in wacc_range:
                row_z = []
                for t in tg_range:
                    # Logic Check: WACC must be > TG + Buffer for Math Stability
                    if w <= t + TG_BUFFER:
                        row_z.append(np.nan) # Invalid combination
                    else:
                        p_df, p_tv, _ = project_financials(latest, w, s_pg, t, years=10)
                        val, _ = calculate_valuation(latest, p_df, p_tv)
                        row_z.append(val)
                z_values.append(row_z)
                
            fig_heat = go.Figure(data=go.Heatmap(
                z=z_values,
                x=[f"{t:.1%}" for t in tg_range],
                y=[f"{w:.1%}" for w in wacc_range],
                colorscale='RdBu',
                texttemplate="₹%{z:.0f}"
            ))
            # Reverse Y-axis so higher WACC (lower value) is at bottom/top consistent with finance intuition
            fig_heat.update_layout(
                title="Target Price Sensitivity (WACC vs Terminal Growth)", 
                xaxis_title="Terminal Growth", 
                yaxis_title="WACC",
                yaxis=dict(autorange="reversed")
            )
            fig_heat = format_chart(fig_heat)
            st.plotly_chart(fig_heat, use_container_width=True)
            
            st.info(f"Implied P/E at Target Price: {pe_display}")

        # Tab 4: Peer Comparison
        with t4:
            st.subheader("Comparable Company Analysis (CCA)")
            st.markdown("Benchmarking key valuation multiples and operating metrics across the peer group.")
            
            # Aggregate Peer Data
            peers = []
            for t in sheets:
                # Include ALL companies in comparison (no exclusions)
                d = process_data(raw_data[t].copy()).iloc[-1]
                
                # EBITDA Margin Safety (Avoid small denom)
                if d['Revenue'] > 1: # > 1 Crore to avoid division by near-zero
                    ebitda_margin = (d['EBITDA'] / d['Revenue']) * 100
                    net_margin = (d['Net_Income'] / d['Revenue']) * 100
                else:
                    ebitda_margin = 0
                    net_margin = 0
                
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
            
            if not peer_df.empty:
                # Calculate Relative Valuation
                # Filter peers excluding target for valuation derivation (Standard Practice: Don't value target based on itself)
                valuation_peers = peer_df[peer_df.index != ticker]
                
                if not valuation_peers.empty:
                    median_pe = valuation_peers['P/E Ratio'].median()
                    median_ev_ebitda = valuation_peers['EV/EBITDA'].median()
                    
                    # Target Metrics for Implied Calculation
                    target_eps = latest['Net_Income'] / latest['Shares_Outstanding']
                    target_ebitda = latest['EBITDA']
                    target_net_debt = latest['Total_Debt'] - latest['Cash_Equivalents']
                    
                    # 1. P/E Valuation
                    implied_price_pe = median_pe * target_eps
                    
                    # 2. EV/EBITDA Valuation
                    implied_ev = median_ev_ebitda * target_ebitda
                    implied_equity_ev = implied_ev - target_net_debt
                    implied_price_ev = implied_equity_ev / latest['Shares_Outstanding']
                    
                    # Display Valuation Card
                    st.markdown("### 🏷️ Relative Valuation (Implied Intrinsic Value)")
                    st.markdown("Calculated using the median multiples of the peer group (excluding target).")
                    
                    rv1, rv2 = st.columns(2)
                    with rv1:
                        st.markdown('<div class="content-card">', unsafe_allow_html=True)
                        st.metric(label="Implied Price (P/E Basis)", value=f"₹ {implied_price_pe:,.2f}", delta=f"Median P/E: {median_pe:.1f}x")
                        st.markdown('</div>', unsafe_allow_html=True)
                    with rv2:
                        st.markdown('<div class="content-card">', unsafe_allow_html=True)
                        st.metric(label="Implied Price (EV/EBITDA Basis)", value=f"₹ {implied_price_ev:,.2f}", delta=f"Median EV/EBITDA: {median_ev_ebitda:.1f}x")
                        st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.warning("Insufficient peers for Relative Valuation calculation.")
                    implied_price_pe = None
                    implied_price_ev = None

                # Display Comparative Table
                st.markdown('<div class="content-card">', unsafe_allow_html=True)
                st.dataframe(peer_df.style.format("{:.2f}").background_gradient(cmap="Blues"), use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
                # Visual Comparison Charts
                col_v1, col_v2 = st.columns(2)
                
                with col_v1:
                    st.markdown('<div class="content-card">', unsafe_allow_html=True)
                    # Scatter Plot for Valuation vs Profitability
                    fig_scatter = px.scatter(peer_df, x='ROE (%)', y='P/E Ratio', text=peer_df.index, size='Revenue (Cr)', title="P/E vs ROE (Size = Revenue)", color=peer_df.index)
                    fig_scatter.update_traces(textposition='top center')
                    fig_scatter = format_chart(fig_scatter)
                    st.plotly_chart(fig_scatter, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                with col_v2:
                    st.markdown('<div class="content-card">', unsafe_allow_html=True)
                    # Grouped Bar for Multiples
                    fig_ev = go.Figure()
                    fig_ev.add_trace(go.Bar(x=peer_df.index, y=peer_df['P/E Ratio'], name='P/E'))
                    fig_ev.add_trace(go.Bar(x=peer_df.index, y=peer_df['EV/EBITDA'], name='EV/EBITDA'))
                    fig_ev.update_layout(title="Valuation Multiples", barmode='group')
                    fig_ev = format_chart(fig_ev)
                    st.plotly_chart(fig_ev, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                
                st.markdown("### Profitability & Efficiency Comparison")
                col_p1, col_p2 = st.columns(2)
                
                with col_p1:
                    st.markdown('<div class="content-card">', unsafe_allow_html=True)
                    fig_roe = px.bar(peer_df, x=peer_df.index, y='ROE (%)', title="Return on Equity (ROE)", color=peer_df.index, text_auto='.1f')
                    fig_roe = format_chart(fig_roe)
                    st.plotly_chart(fig_roe, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                with col_p2:
                    st.markdown('<div class="content-card">', unsafe_allow_html=True)
                    fig_marg = go.Figure()
                    fig_marg.add_trace(go.Bar(x=peer_df.index, y=peer_df['EBITDA Margin (%)'], name='EBITDA Margin'))
                    fig_marg.add_trace(go.Bar(x=peer_df.index, y=peer_df['Net Profit Margin (%)'], name='Net Margin'))
                    fig_marg.update_layout(title="Operating Margins", barmode='group')
                    fig_marg = format_chart(fig_marg)
                    st.plotly_chart(fig_marg, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("No peers available for comparison (only 1 company in dataset).")
                implied_price_pe = None
                implied_price_ev = None
                
        # Tab 5: Report
        with t5:
            st.markdown("### Generate Investment Note")
            
            if st.button("Download PDF Report"):
                # Use retrieved relative values if they exist in scope (calculated in t4)
                # Need to ensure they are available even if t4 wasn't clicked first (Streamlit rerun logic usually handles this if defined in main flow, 
                # but to be safe we'll recalc if needed or rely on script execution order)
                
                # Recalculating relative values for PDF safety since they are inside the t4 block
                # A cleaner way is to move calc outside, but for now we'll re-run light calc or rely on scope.
                # Actually, in Streamlit, variables inside `with t4:` might not be accessible in `with t5:` if t4 hasn't run.
                # Best practice: Move calculation logic *before* the tabs.
                
                # --- RE-CALCULATING FOR PDF SAFETY ---
                if 'peer_df' in locals() and not peer_df.empty:
                    val_peers = peer_df[peer_df.index != ticker]
                    if not val_peers.empty:
                         m_pe = val_peers['P/E Ratio'].median()
                         m_ev = val_peers['EV/EBITDA'].median()
                         pdf_imp_pe = m_pe * (latest['Net_Income'] / latest['Shares_Outstanding'])
                         
                         i_ev = m_ev * latest['EBITDA']
                         i_eq = i_ev - (latest['Total_Debt'] - latest['Cash_Equivalents'])
                         pdf_imp_ev = i_eq / latest['Shares_Outstanding']
                    else:
                        pdf_imp_pe = None
                        pdf_imp_ev = None
                else:
                    pdf_imp_pe = None
                    pdf_imp_ev = None
                    
                pdf_bytes = generate_pdf(ticker, target_price, upside, final_wacc, ke, kd, s_tg, proj_df, latest, peer_df, df, risks, pdf_imp_pe, pdf_imp_ev)
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/pdf;base64,{b64}" download="{ticker}_Valuation_Report.pdf" style="background-color:#2c3e50; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Download PDF File</a>'
                st.markdown(href, unsafe_allow_html=True)
                st.success("Report generated successfully.")
                
    else:
        st.info("👋 Welcome to IFAVP. Please upload the 'fmcg_data_detailed.xlsx' file to begin.")

if __name__ == "__main__":
    main()
