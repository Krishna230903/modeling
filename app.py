import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
from datetime import datetime
import time

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

# --- 3. PREMIUM CORPORATE CSS ---
st.markdown("""
<style>
    /* MAIN BACKGROUND */
    .stApp {
        background-color: #f4f6f9;
    }

    /* SIDEBAR STYLING - Dark Theme */
    section[data-testid="stSidebar"] {
        background-color: #2c3e50;
    }
    section[data-testid="stSidebar"] h1, 
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3, 
    section[data-testid="stSidebar"] label, 
    section[data-testid="stSidebar"] .stMarkdown p {
        color: #ecf0f1 !important;
    }
    section[data-testid="stSidebar"] .stButton button {
        background-color: #e74c3c;
        color: white;
        border: none;
    }
    
    /* CUSTOM METRIC CARD */
    .metric-container {
        background-color: white;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border-left: 5px solid #3498db;
        text-align: center;
        transition: transform 0.2s;
    }
    .metric-container:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0,0,0,0.1);
    }
    .metric-label {
        font-size: 12px;
        color: #7f8c8d;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 5px;
    }
    .metric-value {
        font-size: 26px;
        font-weight: 700;
        color: #2c3e50;
    }
    .metric-delta {
        font-size: 14px;
        font-weight: 500;
        margin-top: 5px;
    }
    .delta-pos { color: #27ae60; }
    .delta-neg { color: #c0392b; }

    /* HEADERS */
    h1, h2, h3 {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #2c3e50;
        font-weight: 600;
    }

    /* LOGIN CARD */
    .login-card {
        background-color: white;
        padding: 40px;
        border-radius: 10px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        text-align: center;
        max-width: 400px;
        margin: 50px auto;
    }
    
    /* TAB STYLING */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background-color: white;
        padding: 10px 10px 0 10px;
        border-radius: 10px 10px 0 0;
        border-bottom: 1px solid #ddd;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        border-radius: 5px 5px 0 0;
        font-weight: 600;
        color: #7f8c8d;
    }
    .stTabs [aria-selected="true"] {
        color: #3498db;
        background-color: #ebf5fb;
    }

</style>
""", unsafe_allow_html=True)

# --- 4. DATA ENGINE ---
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
    df['Net_Margin'] = df['Net_Income'] / df['Revenue']
    df['Asset_Turnover'] = df['Revenue'] / df['Total_Assets']
    df['Leverage'] = df['Total_Assets'] / df['Total_Equity']
    df['ROE'] = df['Net_Margin'] * df['Asset_Turnover'] * df['Leverage']
    df['PE_Ratio'] = df['Avg_Price'] / (df['Net_Income'] / df['Shares_Outstanding'])
    
    market_cap = df['Avg_Price'] * df['Shares_Outstanding']
    df['Enterprise_Value'] = market_cap + df['Total_Debt'] - df['Cash_Equivalents']
    df['EV_EBITDA'] = df['Enterprise_Value'] / df['EBITDA']
    return df

# --- 5. VALUATION ENGINE (DCF) ---
def calculate_dcf(df, wacc, terminal_growth, proj_growth, fcf_conversion_rate):
    latest = df.iloc[-1]
    years_proj = 5
    
    future_fcf = []
    current_ebitda = latest['EBITDA']
    
    for i in range(years_proj):
        current_ebitda = current_ebitda * (1 + proj_growth)
        fcf = current_ebitda * fcf_conversion_rate
        future_fcf.append(fcf)
        
    last_fcf = future_fcf[-1]
    terminal_value = (last_fcf * (1 + terminal_growth)) / (wacc - terminal_growth)
    
    discount_factors = [(1 + wacc) ** i for i in range(1, years_proj + 1)]
    pv_fcf = [f / d for f, d in zip(future_fcf, discount_factors)]
    pv_terminal = terminal_value / ((1 + wacc) ** years_proj)
    
    enterprise_value = sum(pv_fcf) + pv_terminal
    equity_value = enterprise_value - latest['Total_Debt'] + latest['Cash_Equivalents']
    intrinsic_price = equity_value / latest['Shares_Outstanding']
    
    return intrinsic_price, future_fcf, pv_fcf, pv_terminal, equity_value

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
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Key Financial Metrics (Latest FY)", 0, 1)
    pdf.set_font("Arial", size=11)
    metrics = (
        f"- Revenue: INR {data['Revenue'].iloc[-1]:,.0f} Cr\n"
        f"- EBITDA Margin: {(data['EBITDA'].iloc[-1]/data['Revenue'].iloc[-1])*100:.1f}%\n"
        f"- Net Profit Margin: {(data['Net_Income'].iloc[-1]/data['Revenue'].iloc[-1])*100:.1f}%\n"
        f"- Return on Equity (ROE): {data['ROE'].iloc[-1]*100:.1f}%\n"
        f"- P/E Ratio: {data['PE_Ratio'].iloc[-1]:.1f}x"
    )
    pdf.multi_cell(0, 8, metrics)
    pdf.ln(10)
    return pdf.output(dest='S').encode('latin-1')

# --- 8. UI HELPER FUNCTIONS ---
def display_metric_card(label, value, delta=None):
    delta_html = ""
    if delta:
        color_class = "delta-pos" if delta > 0 else "delta-neg"
        arrow = "▲" if delta > 0 else "▼"
        delta_html = f'<div class="metric-delta {color_class}">{arrow} {abs(delta):.1f}%</div>'
        
    html = f"""
    <div class="metric-container">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        {delta_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# --- 9. AUTHENTICATION SCREENS ---
def login_page():
    # Centered Column
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("""
        <div class="login-card">
            <h2 style="color:#2c3e50;">IFAVP Portal</h2>
            <p style="color:#7f8c8d; font-size: 14px;">Secure Financial Analytics Access</p>
            <hr style="margin: 20px 0; border-top: 1px solid #eee;">
        </div>
        """, unsafe_allow_html=True)
        
        tab_login, tab_signup = st.tabs(["🔒 Secure Login", "📝 New Registration"])
        
        with tab_login:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                st.markdown("<br>", unsafe_allow_html=True)
                submit = st.form_submit_button("Access Dashboard", use_container_width=True)
                
                if submit:
                    if username in st.session_state['users'] and st.session_state['users'][username] == password:
                        st.session_state['authenticated'] = True
                        st.session_state['user'] = username
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")
        
        with tab_signup:
            with st.form("signup_form"):
                new_user = st.text_input("New Username")
                new_pass = st.text_input("New Password", type="password")
                confirm_pass = st.text_input("Confirm Password", type="password")
                st.markdown("<br>", unsafe_allow_html=True)
                signup_submit = st.form_submit_button("Create Account", use_container_width=True)
                
                if signup_submit:
                    if new_user in st.session_state['users']:
                        st.error("User already exists.")
                    elif new_pass != confirm_pass:
                        st.error("Passwords do not match.")
                    elif len(new_pass) < 1:
                        st.error("Password cannot be empty.")
                    else:
                        st.session_state['users'][new_user] = new_pass
                        st.success("Account created! Please login.")

# --- 10. MAIN DASHBOARD ---
def dashboard():
    # SIDEBAR
    st.sidebar.markdown("""
    <div style="text-align: center; padding: 10px 0;">
        <h2 style="color: white; margin: 0;">IFAVP</h2>
        <p style="color: #bdc3c7; font-size: 12px; margin: 0;">INSTITUTIONAL GRADE ANALYTICS</p>
    </div>
    <hr style="border-top: 1px solid #34495e;">
    """, unsafe_allow_html=True)
    
    st.sidebar.markdown(f"**Analyst:** {st.session_state['user']}")
    
    if st.sidebar.button("Log Out"):
        st.session_state['authenticated'] = False
        st.session_state['user'] = None
        st.rerun()
        
    st.sidebar.markdown("### 📂 Data Management")
    uploaded_file = st.sidebar.file_uploader("Upload Data File (XLSX)", type=["xlsx"])

    if uploaded_file:
        raw_data, companies = load_data(uploaded_file)
        
        if raw_data is None:
            return

        st.sidebar.markdown("### 🏢 Entity Selection")
        selected_ticker = st.sidebar.selectbox("Choose Company", companies, label_visibility="collapsed")
        
        if not selected_ticker:
            st.warning("No companies found in the uploaded file.")
            return

        df_raw = raw_data[selected_ticker].copy()
        df = process_metrics(df_raw)
        
        # Assumptions in Expander to save space
        with st.sidebar.expander("⚙️ Valuation Assumptions", expanded=True):
            wacc = st.slider("WACC (%)", 8.0, 15.0, 11.5, 0.1) / 100
            term_growth = st.slider("Terminal Growth (%)", 3.0, 8.0, 5.0, 0.5) / 100
            proj_growth = st.slider("Proj. Growth (%)", 0.0, 20.0, 10.0, 1.0) / 100
        
        # Main Header
        st.title(f"{selected_ticker} Financial Analysis")
        st.markdown(f"**Reporting Currency:** INR (Crores) | **Valuation Date:** {datetime.now().strftime('%Y-%m-%d')}")
        st.markdown("---")
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # CUSTOM METRIC CARDS
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            rev_growth = ((latest['Revenue']-prev['Revenue'])/prev['Revenue']*100)
            display_metric_card("Total Revenue", f"₹ {latest['Revenue']:,.0f}", rev_growth)
        with k2:
            prof_growth = ((latest['Net_Income']-prev['Net_Income'])/prev['Net_Income']*100)
            display_metric_card("Net Profit", f"₹ {latest['Net_Income']:,.0f}", prof_growth)
        with k3:
            display_metric_card("EBITDA Margin", f"{(latest['EBITDA']/latest['Revenue']*100):.1f}%")
        with k4:
            display_metric_card("Market Price", f"₹ {latest['Avg_Price']:,.2f}")
        
        st.markdown("<br>", unsafe_allow_html=True)

        # Tabs
        tabs = st.tabs(["📊 Performance", "💰 Valuation", "🎲 Risk Lab", "⚖️ Peers", "📄 Report"])
        
        # Tab 1: Performance
        with tabs[0]:
            st.subheader("Financial Health Assessment")
            
            fig_dupont = go.Figure()
            fig_dupont.add_trace(go.Bar(x=df['Year'], y=df['ROE']*100, name='ROE %', marker_color='#2c3e50', opacity=0.8))
            fig_dupont.add_trace(go.Scatter(x=df['Year'], y=df['Net_Margin']*100, name='Net Margin %', line=dict(color='#e74c3c', width=3)))
            fig_dupont.update_layout(
                title="DuPont Analysis: ROE Drivers", 
                hovermode="x unified", 
                legend=dict(orientation="h", y=1.1),
                plot_bgcolor='white',
                paper_bgcolor='white',
                font=dict(family="Helvetica Neue", color="#2c3e50")
            )
            st.plotly_chart(fig_dupont, use_container_width=True)
            
            c1, c2 = st.columns(2)
            with c1:
                fig_rev = px.bar(df, x='Year', y='Revenue', title="Revenue Trajectory", color_discrete_sequence=['#3498db'])
                fig_rev.update_layout(plot_bgcolor='white')
                st.plotly_chart(fig_rev, use_container_width=True)
            with c2:
                fig_eps = px.line(df, x='Year', y='Net_Income', title="Net Profit Growth", color_discrete_sequence=['#2ecc71'])
                fig_eps.update_layout(plot_bgcolor='white')
                st.plotly_chart(fig_eps, use_container_width=True)

        # Tab 2: Valuation
        with tabs[1]:
            st.subheader("Discounted Cash Flow (DCF) Model")
            
            intrinsic_val, future_fcf, pv_fcf, pv_term, equity_val = calculate_dcf(df, wacc, term_growth, proj_growth, 0.6)
            curr_price = latest['Avg_Price']
            upside = ((intrinsic_val - curr_price) / curr_price) * 100
            
            v1, v2 = st.columns([1, 2])
            with v1:
                st.markdown("""
                <div style="background-color: white; padding: 20px; border-radius: 8px; border: 1px solid #eee;">
                    <h4 style="margin-top:0;">Valuation Conclusion</h4>
                    <hr>
                </div>
                """, unsafe_allow_html=True)
                st.metric("Intrinsic Value", f"₹ {intrinsic_val:,.2f}")
                st.metric("Market Price", f"₹ {curr_price:,.2f}")
                
                if upside > 0:
                    st.success(f"Undervalued by {upside:.1f}%")
                else:
                    st.error(f"Overvalued by {abs(upside):.1f}%")
            
            with v2:
                fig_water = go.Figure(go.Waterfall(
                    measure = ["relative", "relative", "total", "relative", "relative", "total"],
                    x = ["PV of FCF", "PV Terminal", "Enterprise Value", "Less Debt", "Add Cash", "Equity Value"],
                    y = [sum(pv_fcf), pv_term, 0, -latest['Total_Debt'], latest['Cash_Equivalents'], 0],
                    connector = {"line":{"color":"#333"}}
                ))
                fig_water.update_layout(title="Valuation Bridge (INR Cr)", plot_bgcolor='white')
                st.plotly_chart(fig_water, use_container_width=True)

        # Tab 3: Risk
        with tabs[2]:
            st.subheader("Risk Sensitivity & Simulation")
            r1, r2 = st.columns(2)
            
            with r1:
                st.markdown("#### Sensitivity Heatmap")
                wacc_range = np.linspace(wacc - 0.02, wacc + 0.02, 5)
                growth_range = np.linspace(term_growth - 0.01, term_growth + 0.01, 5)
                z_values = []
                for w in wacc_range:
                    row = []
                    for g in growth_range:
                        val, _, _, _, _ = calculate_dcf(df, w, g, proj_growth, 0.6)
                        row.append(val)
                    z_values.append(row)
                
                fig_heat = go.Figure(data=go.Heatmap(
                    z=z_values,
                    x=[f"{g*100:.1f}%" for g in growth_range],
                    y=[f"{w*100:.1f}%" for w in wacc_range],
                    colorscale='Blues'))
                fig_heat.update_layout(title="Share Price vs Assumptions", xaxis_title="Terminal Growth", yaxis_title="WACC")
                st.plotly_chart(fig_heat, use_container_width=True)

            with r2:
                st.markdown("#### Monte Carlo Simulation")
                vol = st.slider("Volatility Assumption (%)", 10, 50, 25) / 100
                paths = run_monte_carlo(curr_price, vol)
                fig_mc = go.Figure()
                for i in range(30):
                    fig_mc.add_trace(go.Scatter(y=paths[:, i], mode='lines', opacity=0.15, showlegend=False, line=dict(color='#34495e')))
                fig_mc.add_trace(go.Scatter(y=np.mean(paths, axis=1), mode='lines', name='Mean Path', line=dict(color='#c0392b', width=2)))
                fig_mc.update_layout(title="Projected Price Paths (1 Year)", xaxis_title="Trading Days", yaxis_title="Price", plot_bgcolor='white')
                st.plotly_chart(fig_mc, use_container_width=True)

        # Tab 4: Peers
        with tabs[3]:
            st.subheader("Peer Benchmarking")
            peers_data = []
            for comp, data in raw_data.items():
                d = process_metrics(data.copy()).iloc[-1]
                peers_data.append({
                    "Entity": comp,
                    "Revenue": d['Revenue'],
                    "EBITDA Margin": d['EBITDA']/d['Revenue'],
                    "ROE": d['ROE'],
                    "P/E": d['PE_Ratio'],
                    "EV/EBITDA": d['EV_EBITDA']
                })
            
            peer_df = pd.DataFrame(peers_data).set_index('Entity')
            
            # Use columns to make table centered
            c1, c2, c3 = st.columns([1, 4, 1])
            with c2:
                st.dataframe(peer_df.style.format({
                    "Revenue": "{:,.0f}",
                    "EBITDA Margin": "{:.1%}",
                    "ROE": "{:.1%}",
                    "P/E": "{:.1f}x",
                    "EV/EBITDA": "{:.1f}x"
                }).background_gradient(cmap="Blues", subset=['ROE', 'EBITDA Margin']), use_container_width=True)

        # Tab 5: Report
        with tabs[4]:
            st.subheader("Investment Committee Report")
            col_gen, col_empty = st.columns([1, 2])
            with col_gen:
                st.info("Generate a standardized PDF investment note for internal review.")
                if st.button("📄 Generate Report PDF"):
                    pdf_bytes = generate_pdf(selected_ticker, df, intrinsic_val, upside)
                    b64 = base64.b64encode(pdf_bytes).decode()
                    href = f'<a href="data:application/octet-stream;base64,{b64}" download="{selected_ticker}_Valuation_Report.pdf" style="text-decoration:none; color:white; background-color:#27ae60; padding:10px 20px; border-radius:5px; display:inline-block;">Download PDF Report</a>'
                    st.markdown(href, unsafe_allow_html=True)

    else:
        # Empty State
        st.markdown("""
        <div style="text-align: center; margin-top: 50px;">
            <h3 style="color: #bdc3c7;">Waiting for Data Input...</h3>
            <p style="color: #95a5a6;">Please upload the Master Data File via the sidebar to initialize the dashboard.</p>
        </div>
        """, unsafe_allow_html=True)

# --- 11. MAIN APP CONTROLLER ---
def main():
    if not st.session_state['authenticated']:
        login_page()
    else:
        dashboard()

if __name__ == "__main__":
    main()
