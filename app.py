import streamlit as st
import pandas as pd
import plotly.express as px
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta

# --- CONFIGURATION ---
REGULATORY_MAP = {
    "OCC": {"identifier": "Comptroller", "keywords": [r"Target Date", r"Commitment Date", r"Completion Date"]},
    "FRB": {"identifier": "Federal Reserve", "keywords": [r"Timeline", r"Due Date", r"Expectation Date", r"Required Action"]}
}

def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

# --- EXTRACTION ENGINE ---
def extract_mras_from_pdf(pdf_bytes, filename):
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc: text += page.get_text()

    agency = "FRB" if REGULATORY_MAP["FRB"]["identifier"] in text else "OCC"
    keywords = REGULATORY_MAP[agency]["keywords"]
    date_matches = re.findall(rf"(?:{'|'.join(keywords)})[:\s]*(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})", text, re.IGNORECASE)

    extracted_findings = []
    # Force standard naive datetime for 2026 system compatibility
    today_naive = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    
    for i, date_str in enumerate(date_matches if date_matches else ["Placeholder"]):
        try:
            deadline = pd.to_datetime(date_str).to_pydatetime().replace(tzinfo=None)
        except:
            deadline = today_naive + timedelta(days=90)

        extracted_findings.append({
            "MRA_ID": f"{agency}-{filename[:5].upper()}-{i+1:02}",
            "Agency": agency,
            "Owner": "LOB Pending",
            "Start_Date": today_naive - timedelta(days=90),
            "Deadline": deadline,
            "Status": "In Progress"
        })
    return pd.DataFrame(extracted_findings)

# --- EARLY WARNING & OVERDUE LOGIC ---
def apply_sentinel_logic(df, auto_fix=False):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    
    # Ensure strict datetime types
    df['Deadline'] = pd.to_datetime(df['Deadline']).dt.tz_localize(None)
    df['Start_Date'] = pd.to_datetime(df['Start_Date']).dt.tz_localize(None)

    def process_row(row):
        # Calculate Delta
        delta = (row['Deadline'] - today).days
        row['Days_Remaining'] = delta if row['Status'] != "Closed" else 0
        
        # Risk Logic
        if row['Status'] == "Closed": 
            row['Risk_Status'] = "✅ Closed"
        elif delta < 0:
            row['Risk_Status'] = "💀 OVERDUE"
        elif row['Start_Date'] >= row['Deadline']:
            if auto_fix:
                row['Start_Date'] = row['Deadline'] - timedelta(days=90)
                row['Risk_Status'] = "🟢 Fixed"
            else:
                row['Risk_Status'] = "❌ Error: Invalid Dates"
        else:
            total_window = (row['Deadline'] - row['Start_Date']).days
            elapsed = (today - row['Start_Date']).days
            burn_rate = elapsed / total_window if total_window > 0 else 1
            if burn_rate >= 0.75: row['Risk_Status'] = "🚨 CRITICAL: 75%+ Elapsed"
            elif burn_rate >= 0.50: row['Risk_Status'] = "⚠️ WARNING: 50% Elapsed"
            else: row['Risk_Status'] = "🟢 On Track"
        return row

    return df.apply(process_row, axis=1)

# --- UI SETUP ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")
st.title("🛡️ MRA Sentinel: Command Center")

st.sidebar.header("Sentinel Controls")
auto_fix_enabled = st.sidebar.toggle("Enable Auto-Fix Dates", value=True)
if st.sidebar.button("🗑️ Clear Master Tracker"):
    st.session_state.mra_data = pd.DataFrame()
    st.rerun()

if "mra_data" not in st.session_state:
    st.session_state.mra_data = pd.DataFrame()

uploaded_files = st.file_uploader("Batch Upload PDFs", type=["pdf"], accept_multiple_files=True)
if uploaded_files:
    if st.button("🚀 Ingest Findings"):
        new_records = [extract_mras_from_pdf(f.read(), f.name) for f in uploaded_files]
        combined = pd.concat([st.session_state.mra_data, *new_records], ignore_index=True)
        st.session_state.mra_data = apply_sentinel_logic(combined, auto_fix=auto_fix_enabled).drop_duplicates(subset=['MRA_ID'])

if not st.session_state.mra_data.empty:
    # 1. ANALYTICS
    st.subheader("📊 Portfolio Risk Analytics")
    col1, col2, col3 = st.columns([1, 1.5, 2])
    with col1:
        st.metric("Master Inventory", len(st.session_state.mra_data))
        crit = len(st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀")])
        st.metric("Risk Items", crit, delta_color="inverse")
    with col2:
        dist = st.session_state.mra_data['Risk_Status'].value_counts().reset_index()
        dist.columns = ['Risk_Status', 'count']
        fig_donut = px.pie(dist, values='count', names='Risk_Status', hole=0.5, 
                           color='Risk_Status', color_discrete_map={"💀 OVERDUE": "#000000", "🚨 CRITICAL: 75%+ Elapsed": "#FF4B4B", "⚠️ WARNING: 50% Elapsed": "#FFAA00", "🟢 On Track": "#00CC96", "✅ Closed": "#2E7D32"})
        st.plotly_chart(fig_donut, use_container_width=True)
    with col3:
        heat = st.session_state.mra_data.groupby(['Owner', 'Risk_Status']).size().unstack(fill_value=0)
        fig_heat = px.bar(heat, barmode="stack", color_discrete_sequence=["#1B263B", "#415A77", "#778DA9"])
        st.plotly_chart(fig_heat, use_container_width=True)

    # 2. LEDGER
    st.subheader("📋 Centralized Remediation Ledger")
    edited_df = st.data_editor(st.session_state.mra_data, use_container_width=True, num_rows="dynamic")
    st.session_state.mra_data = apply_sentinel_logic(edited_df, auto_fix=auto_fix_enabled)

    # 3. ROADMAP
    tab1, tab2 = st.tabs(["🗺️ Strategic Roadmap", "📧 Alerts"])
    with tab1:
        chart_df = st.session_state.mra_data.copy()
        
        # --- THE CRITICAL FIX: CHRONOLOGY FORCING ---
        # Plotly crashes on Start > Deadline. We force a 30-day visual bar for overdue items.
        def fix_for_chart(row):
            if row['Start_Date'] >= row['Deadline']:
                row['Start_Date'] = row['Deadline'] - timedelta(days=30)
            return row
        
        chart_df = chart_df.apply(fix_for_chart, axis=1)
        chart_df['MRA_ID'] = chart_df['MRA_ID'].astype(str)
        chart_df = chart_df.dropna(subset=['Start_Date', 'Deadline']).reset_index(drop=True)

        if not chart_df.empty:
            fig_gantt = px.timeline(
                chart_df, start="Start_Date", end="Deadline", x_start="Start_Date", x_end="Deadline", 
                y="MRA_ID", color="Risk_Status", 
                color_discrete_map={"💀 OVERDUE": "#000000", "🚨 CRITICAL: 75%+ Elapsed": "#FF4B4B", "⚠️ WARNING: 50% Elapsed": "#FFAA00", "🟢 On Track": "#00CC96", "✅ Closed": "#2E7D32"}
            )
            fig_gantt.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_gantt, use_container_width=True)
        else:
            st.warning("Roadmap hidden: No valid items.")

    st.download_button("📥 Export CSV", convert_df_to_csv(st.session_state.mra_data), "MRA_Sentinel_Export.csv", "text/csv")
