import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
from datetime import datetime
import time
import yfinance as yf

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="IFAVP | Institutional Analytics",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="📊"
)

# --- 2. SESSION STATE (AUTH) ---
if 'users' not in st.session_state:
    st.session_state['users'] = {'admin': 'password123'} # Default credentials
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
if 'user' not in st.session_state:
    st.session_state['user'] = None

# --- 3. PREMIUM CORPORATE CSS (High Contrast) ---
st.markdown("""
<style>
    /* MAIN LAYOUT & TYPOGRAPHY */
    html, body, [class*="css"] {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #333333;
    }
    
    /* BACKGROUNDS */
    .stApp {
        background-color: #ffffff;
    }
    
    /* SIDEBAR */
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
    
    /* METRIC CARDS */
    div[data-testid="stMetricValue"] {
        color: #2c3e50 !important;
        font-weight: 700;
    }
    div[data-testid="stMetricLabel"] {
        color: #7f8c8d !important;
    }

    /* CUSTOM CARDS */
    .custom-card {
        background-color: #f8f9fa;
        padding: 20px;
        border-radius: 8px;
        border: 1px solid #e9ecef;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    .live-card {
        background-color: #e8f6f3;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #d1f2eb;
        border-left: 4px solid #1abc9c;
        margin-bottom: 20px;
    }
    .card-title {
        color: #2c3e50;
        font-weight: 600;
        font-size: 1.1rem;
        margin-bottom: 10px;
        border-bottom: 2px solid #3498db;
        padding-bottom: 5px;
    }

    /* TABLES */
    thead tr th {
        background-color: #f1f3f5 !important;
        color: #2c3e50 !important;
        font-weight: 600 !important;
    }
    tbody tr:nth-child(even) {
        background-color: #f8f9fa;
    }

    /* TABS */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #ffffff;
        border-bottom: 1px solid #dee2e6;
    }
    .stTabs [data-baseweb="tab"] {
        height: 45px;
        color: #495057;
        font-weight: 500;
        border: 1px solid transparent;
        border-bottom: none;
    }
    .stTabs [aria-selected="true"] {
        color: #2c3e50;
        background-color: #e9ecef;
        border-bottom: 2px solid #2c3e50;
    }
</style>
""", unsafe_allow_html=True)

# --- 4. DATA ENGINE ---
TICKER_MAP = {
    'HUL': 'HINDUNILVR.NS',
    'ITC': 'ITC.NS',
    'COLPAL': 'COLPAL.NS',
    'COLGATE': 'COLPAL.NS',
    'NESTLE': 'NESTLEIND.NS',
    'BRITANNIA': 'BRITANNIA.NS',
    'HINDUSTAN UNILEVER': 'HINDUNILVR.NS'
}

@st.cache_data
def load_data(file):
    try:
        xl = pd.ExcelFile(file)
        sheet_names = xl.sheet_names
        data_dict = {sheet: xl.parse(sheet) for sheet in sheet_names}
        return data_dict, sheet_names
    except Exception as e:
        st.error(f"System Error: Unable to load file. Details: {e}")
        return None, []

def process_metrics(df):
    cols_to_numeric = ['Revenue', 'Net_Income', 'Total_Assets', 'Total_Equity', 'Avg_Price', 'Shares_Outstanding', 'Total_Debt', 'Cash_Equivalents', 'EBITDA']
    for col in cols_to_numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    df['Net_Margin'] = df['Net_Income'] / df['Revenue']
    df['Asset_Turnover'] = df['Revenue'] / df['Total_Assets']
    df['Leverage'] = df['Total_Assets'] / df['Total_Equity']
    df['ROE'] = df['Net_Margin'] * df['Asset_Turnover'] * df['Leverage']
    df['PE_Ratio'] = df['Avg_Price'] / (df['Net_Income'] / df['Shares_Outstanding'])
    
    market_cap = df['Avg_Price'] * df['Shares_Outstanding']
    df['Enterprise_Value'] = market_cap + df['Total_Debt'] - df['Cash_Equivalents']
    df['EV_EBITDA'] = df['Enterprise_Value'] / df['EBITDA']
    return df

# --- 5. VALUATION ENGINE (Detailed DCF) ---
def calculate_dcf(df, wacc, terminal_growth, proj_growth, fcf_conversion_rate):
    latest = df.iloc[-1]
    years_proj = 5
    projection_data = []
    
    current_revenue = latest['Revenue']
    current_ebitda_margin = latest['EBITDA'] / latest['Revenue'] if latest['Revenue'] > 0 else 0
    
    future_fcf = []
    
    for i in range(1, years_proj + 1):
        proj_rev = current_revenue * ((1 + proj_growth) ** i)
        proj_ebitda = proj_rev * current_ebitda_margin
        proj_fcf = proj_ebitda * fcf_conversion_rate
        
        disc_factor = (1 + wacc) ** i
        pv_fcf = proj_fcf / disc_factor
        future_fcf.append(proj_fcf)
        
        projection_data.append({
            "Year": f"Year {i}",
            "Revenue": proj_rev,
            "EBITDA": proj_ebitda,
            "Free Cash Flow (FCF)": proj_fcf,
            "Discount Factor": 1/disc_factor,
            "PV of FCF": pv_fcf
        })
    
    last_fcf = future_fcf[-1]
    terminal_value = (last_fcf * (1 + terminal_growth)) / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1 + wacc) ** years_proj)
    
    sum_pv_fcf = sum([d['PV of FCF'] for d in projection_data])
    enterprise_value = sum_pv_fcf + pv_terminal
    
    equity_value = enterprise_value - latest['Total_Debt'] + latest['Cash_Equivalents']
    intrinsic_price = equity_value / latest['Shares_Outstanding']
    
    return intrinsic_price, pd.DataFrame(projection_data), pv_terminal, equity_value

# --- 6. RISK ENGINE ---
def run_monte_carlo(current_price, volatility, simulations=1000, days=252):
    dt = 1/days
    price_paths = np.zeros((days, simulations))
    price_paths[0] = current_price
    drift = 0.10 
    
    for t in range(1, days):
        rand = np.random.standard_normal(simulations)
        shock = volatility * np.sqrt(dt) * rand
        price_paths[t] = price_paths[t-1] * np.exp((drift - 0.5 * volatility**2) * dt + shock)
        
    return price_paths

# --- 7. REPORTING ENGINE ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'IFAVP - Valuation Report', 0, 1, 'R')
        self.line(10, 20, 200, 20)
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()} | Generated by Intelligent Financial Analytics Platform', 0, 0, 'C')

def generate_pdf(ticker, data, valuation, upside):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"Investment Note: {ticker}", 0, 1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%d %B %Y')}", 0, 1)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Executive Summary", 0, 1)
    pdf.set_font("Arial", size=11)
    
    summary = (
        f"We have conducted a valuation analysis of {ticker} using the Discounted Cash Flow (DCF) methodology. "
        f"Based on our projections and assumptions (WACC, Terminal Growth), the estimated Intrinsic Value is INR {valuation:,.2f} per share.\n\n"
        f"Comparison with Market:\n"
        f"- Current Market Price: INR {data['Avg_Price'].iloc[-1]:,.2f}\n"
        f"- Implied Upside/Downside: {upside:.1f}%\n"
    )
    pdf.multi_cell(0, 8, summary)
    pdf.ln(5)
    return pdf.output(dest='S').encode('latin-1')

# --- 8. AUTHENTICATION SCREENS ---
def login_page():
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("""
        <div style="background-color: white; padding: 40px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); text-align: center; border: 1px solid #ddd;">
            <h2 style="color:#2c3e50; margin-bottom: 5px;">IFAVP Portal</h2>
            <p style="color:#7f8c8d; font-size: 14px;">Institutional Access</p>
        </div>
        <br>
        """, unsafe_allow_html=True)
        
        with st.form("login_form"):
            st.markdown("### Secure Login")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Access Dashboard", use_container_width=True)
            
            if submit:
                if username in st.session_state['users'] and st.session_state['users'][username] == password:
                    st.session_state['authenticated'] = True
                    st.session_state['user'] = username
                    st.rerun()
                else:
                    st.error("Invalid credentials.")

# --- 9. MAIN DASHBOARD ---
def dashboard():
    # --- SIDEBAR ---
    st.sidebar.markdown("""
    <div style="text-align: center; padding: 20px 0;">
        <h2 style="color: white; margin: 0; letter-spacing: 2px;">IFAVP</h2>
        <p style="color: #bdc3c7; font-size: 10px; margin: 0;">ANALYTICS SUITE v2.5</p>
    </div>
    <hr style="border-top: 1px solid #34495e;">
    """, unsafe_allow_html=True)
    
    st.sidebar.markdown(f"**Analyst:** {st.session_state['user']}")
    if st.sidebar.button("Log Out"):
        st.session_state['authenticated'] = False
        st.session_state['user'] = None
        st.rerun()

    st.sidebar.markdown("### 📂 Data Source")
    uploaded_file = st.sidebar.file_uploader("Upload Excel Model", type=["xlsx"])

    if uploaded_file:
        raw_data, companies = load_data(uploaded_file)
        
        if raw_data is None:
            return

        st.sidebar.markdown("### 🏢 Entity Focus")
        selected_ticker = st.sidebar.selectbox("Select Company", companies)
        
        # Process selected company
        df_raw = raw_data[selected_ticker].copy()
        df = process_metrics(df_raw)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # --- FETCH LIVE DATA ---
        y_ticker = TICKER_MAP.get(selected_ticker.upper(), None)
        live_price = None
        live_change = 0.0
        
        if y_ticker:
            try:
                stock = yf.Ticker(y_ticker)
                info = stock.fast_info
                live_price = info.last_price
                prev_close = info.previous_close
                live_change = ((live_price - prev_close) / prev_close) * 100
            except:
                pass

        # Assumptions Sidebar
        with st.sidebar.expander("⚙️ DCF Parameters", expanded=True):
            wacc = st.slider("WACC (%)", 5.0, 18.0, 11.0, 0.5) / 100
            term_growth = st.slider("Terminal Growth (%)", 1.0, 10.0, 5.0, 0.5) / 100
            proj_growth = st.slider("Rev Growth (%)", 0.0, 25.0, 10.0, 1.0) / 100
            fcf_conv = st.slider("EBITDA->FCF Conv (%)", 30, 90, 60, 5) / 100

        # --- MAIN CONTENT AREA ---
        st.title(f"{selected_ticker}")
        st.markdown(f"**Reporting Currency:** INR (Crores) | **Valuation Date:** {datetime.now().strftime('%Y-%m-%d')}")
        
        if live_price:
            st.markdown(f"""
            <div class="live-card">
                <span style="font-weight:bold; font-size:1.1rem;">⚡ Live Market Reference ({y_ticker})</span>: 
                <span style="font-size:1.5rem; margin-left:10px;">₹ {live_price:,.2f}</span>
                <span style="color: {'#27ae60' if live_change > 0 else '#c0392b'}; margin-left:10px; font-weight:600;">
                    {live_change:+.2f}%
                </span>
                <span style="float:right; color:#7f8c8d; font-size:0.9rem; margin-top:5px;">Real-time via Yahoo Finance</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("---")
        
        # KPI ROW
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Revenue (Book)", f"₹ {latest['Revenue']:,.0f}", f"{((latest['Revenue']-prev['Revenue'])/prev['Revenue']*100):.1f}%")
        k2.metric("Net Income (Book)", f"₹ {latest['Net_Income']:,.0f}", f"{((latest['Net_Income']-prev['Net_Income'])/prev['Net_Income']*100):.1f}%")
        k3.metric("EBITDA Margin", f"{(latest['EBITDA']/latest['Revenue']*100):.1f}%")
        
        # Display Live Price in KPI if available, else Model Price
        price_val = live_price if live_price else latest['Avg_Price']
        price_label = "Live Price" if live_price else "Price (Model)"
        k4.metric(price_label, f"₹ {price_val:,.2f}")
        
        # TABS
        tabs = st.tabs(["📊 Performance", "💰 Valuation", "🎲 Risk Lab", "🏭 Industry Analysis", "📄 Report"])
        
        # --- TAB 1: PERFORMANCE ---
        with tabs[0]:
            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">Historical Financial Trends</div>', unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            with c1:
                fig_rev = px.bar(df, x='Year', y='Revenue', title="Revenue Trajectory", color_discrete_sequence=['#2980b9'])
                fig_rev.update_layout(plot_bgcolor='white', paper_bgcolor='white', font_color='#2c3e50')
                st.plotly_chart(fig_rev, use_container_width=True)
            with c2:
                fig_prof = px.line(df, x='Year', y=['EBITDA', 'Net_Income'], title="Profitability Profile", markers=True)
                fig_prof.update_layout(plot_bgcolor='white', paper_bgcolor='white', font_color='#2c3e50')
                st.plotly_chart(fig_prof, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">DuPont Analysis (ROE Drivers)</div>', unsafe_allow_html=True)
            fig_dupont = go.Figure()
            fig_dupont.add_trace(go.Bar(x=df['Year'], y=df['ROE']*100, name='ROE %', marker_color='#2c3e50', opacity=0.7))
            fig_dupont.add_trace(go.Scatter(x=df['Year'], y=df['Net_Margin']*100, name='Net Margin %', line=dict(color='#e74c3c')))
            fig_dupont.update_layout(hovermode="x unified", legend=dict(orientation="h", y=1.1), plot_bgcolor='white')
            st.plotly_chart(fig_dupont, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # --- TAB 2: VALUATION ---
        with tabs[1]:
            intrinsic_val, proj_df, pv_term, equity_val = calculate_dcf(df, wacc, term_growth, proj_growth, fcf_conv)
            curr_price = live_price if live_price else latest['Avg_Price']
            upside = ((intrinsic_val - curr_price) / curr_price) * 100
            
            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">DCF Model Output</div>', unsafe_allow_html=True)
            
            v1, v2 = st.columns([1, 2])
            with v1:
                st.metric("Target Price (Intrinsic)", f"₹ {intrinsic_val:,.2f}")
                st.metric("Current Market Price", f"₹ {curr_price:,.2f}")
                if upside > 0:
                    st.success(f"Undervalued by {upside:.1f}%")
                else:
                    st.error(f"Overvalued by {abs(upside):.1f}%")
            
            with v2:
                fig_water = go.Figure(go.Waterfall(
                    measure = ["relative", "relative", "total", "relative", "relative", "total"],
                    x = ["PV of FCF (5Yr)", "PV Terminal Val", "Enterprise Value", "Less Debt", "Add Cash", "Equity Value"],
                    y = [proj_df['PV of FCF'].sum(), pv_term, 0, -latest['Total_Debt'], latest['Cash_Equivalents'], 0],
                    connector = {"line":{"color":"#333"}}
                ))
                fig_water.update_layout(title="Valuation Bridge", plot_bgcolor='white', height=300)
                st.plotly_chart(fig_water, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">Projected Cash Flows (Proforma)</div>', unsafe_allow_html=True)
            st.dataframe(proj_df.style.format("{:,.0f}"), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # --- TAB 3: RISK ---
        with tabs[2]:
            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            r1, r2 = st.columns(2)
            with r1:
                st.markdown("**Sensitivity Heatmap**")
                wacc_range = np.linspace(wacc - 0.02, wacc + 0.02, 5)
                growth_range = np.linspace(term_growth - 0.01, term_growth + 0.01, 5)
                z_values = []
                for w in wacc_range:
                    row = []
                    for g in growth_range:
                        val, _, _, _ = calculate_dcf(df, w, g, proj_growth, fcf_conv)
                        row.append(val)
                    z_values.append(row)
                
                fig_heat = go.Figure(data=go.Heatmap(
                    z=z_values,
                    x=[f"{g*100:.1f}%" for g in growth_range],
                    y=[f"{w*100:.1f}%" for w in wacc_range],
                    colorscale='Blues'))
                fig_heat.update_layout(xaxis_title="Terminal Growth", yaxis_title="WACC")
                st.plotly_chart(fig_heat, use_container_width=True)
            
            with r2:
                st.markdown("**Monte Carlo Simulation (1Y)**")
                vol = st.slider("Volatility (%)", 10, 50, 25) / 100
                paths = run_monte_carlo(curr_price, vol)
                fig_mc = go.Figure()
                for i in range(20):
                    fig_mc.add_trace(go.Scatter(y=paths[:, i], mode='lines', opacity=0.1, showlegend=False, line=dict(color='black')))
                fig_mc.add_trace(go.Scatter(y=np.mean(paths, axis=1), mode='lines', name='Average', line=dict(color='red', width=2)))
                st.plotly_chart(fig_mc, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # --- TAB 4: INDUSTRY ANALYSIS ---
        with tabs[3]:
            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">Industry Peer Comparison</div>', unsafe_allow_html=True)
            
            peers_data = []
            for comp, data in raw_data.items():
                d = process_metrics(data.copy()).iloc[-1]
                peers_data.append({
                    "Company": comp,
                    "Revenue": d['Revenue'],
                    "EBITDA Margin": (d['EBITDA']/d['Revenue'])*100 if d['Revenue'] > 0 else 0,
                    "ROE": d['ROE']*100,
                    "P/E Ratio": d['PE_Ratio'],
                    "EV/EBITDA": d['EV_EBITDA']
                })
            
            peer_df = pd.DataFrame(peers_data).set_index('Company')
            
            i1, i2 = st.columns(2)
            with i1:
                fig_pe = px.bar(peer_df, x=peer_df.index, y='P/E Ratio', title="P/E Ratio Comparison", color=peer_df.index)
                fig_pe.update_layout(showlegend=False, plot_bgcolor='white')
                st.plotly_chart(fig_pe, use_container_width=True)
            with i2:
                fig_roe = px.bar(peer_df, x=peer_df.index, y='ROE', title="Return on Equity (%)", color=peer_df.index)
                fig_roe.update_layout(showlegend=False, plot_bgcolor='white')
                st.plotly_chart(fig_roe, use_container_width=True)
                
            st.markdown("### Comparative Data Table")
            st.dataframe(peer_df.style.format("{:.2f}"), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # --- TAB 5: REPORT ---
        with tabs[4]:
            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">Generate Investment Note</div>', unsafe_allow_html=True)
            if st.button("Download PDF Report"):
                pdf_bytes = generate_pdf(selected_ticker, df, intrinsic_val, upside)
                b64 = base64.b64encode(pdf_bytes).decode()
                href = f'<a href="data:application/octet-stream;base64,{b64}" download="{selected_ticker}_Valuation.pdf">Download PDF</a>'
                st.markdown(href, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    else:
        st.markdown("""
        <div style="text-align: center; margin-top: 50px;">
            <h3 style="color: #2c3e50;">Waiting for Data Input...</h3>
            <p style="color: #7f8c8d;">Please upload the Master Data File via the sidebar to initialize the dashboard.</p>
        </div>
        """, unsafe_allow_html=True)

def main():
    if not st.session_state['authenticated']:
        login_page()
    else:
        dashboard()

if __name__ == "__main__":
    main()
