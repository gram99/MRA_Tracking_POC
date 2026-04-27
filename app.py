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
    default_start = (datetime.now() - timedelta(days=1)).replace(tzinfo=None)
    loop_dates = date_matches if date_matches else ["Manual Entry Needed"]
    
    for i, date_str in enumerate(loop_dates):
        try:
            deadline = pd.to_datetime(date_str).replace(tzinfo=None)
        except:
            deadline = (datetime.now() + timedelta(days=90)).replace(tzinfo=None)

        extracted_findings.append({
            "MRA_ID": f"{agency}-{filename[:5].upper()}-{i+1:02}",
            "Source_File": filename,
            "Owner": "LOB Pending",
            "Start_Date": default_start,
            "Deadline": deadline,
            "Status": "In Progress"
        })
    return pd.DataFrame(extracted_findings)

# --- EARLY WARNING LOGIC ---
def apply_early_warning(df, auto_fix=False):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None)
    
    df['Deadline'] = pd.to_datetime(df['Deadline']).dt.tz_localize(None)
    df['Start_Date'] = pd.to_datetime(df['Start_Date']).dt.tz_localize(None)

    def calculate_risk(row):
        if auto_fix and row['Start_Date'] >= row['Deadline']:
            row['Start_Date'] = row['Deadline'] - timedelta(days=90)
        if row['Status'] == "Closed": return "✅ Closed"
        if row['Start_Date'] >= row['Deadline']: return "❌ Error: Invalid Dates"

        total_window = (row['Deadline'] - row['Start_Date']).days
        elapsed = (today - row['Start_Date']).days
        burn_rate = elapsed / total_window if total_window > 0 else 1
        
        if burn_rate >= 0.75: return "🚨 CRITICAL: 75%+ Elapsed"
        if burn_rate >= 0.50: return "⚠️ WARNING: 50% Elapsed"
        return "🟢 On Track"

    df['Risk_Status'] = df.apply(calculate_risk, axis=1)
    return df

# --- UI SETUP ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")
st.title("🛡️ MRA Sentinel: Command Center")

# Sidebar Controls
st.sidebar.header("Sentinel Controls")
auto_fix_enabled = st.sidebar.toggle("Enable Auto-Fix Dates", value=True)

if st.sidebar.button("🗑️ Clear Master Tracker"):
    st.session_state.mra_data = pd.DataFrame()
    st.rerun()

if "mra_data" not in st.session_state:
    st.session_state.mra_data = pd.DataFrame()

# File Upload Section
uploaded_files = st.file_uploader("Batch Upload Regulatory PDFs", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    if st.button("🚀 Ingest Findings"):
        new_records = [extract_mras_from_pdf(f.read(), f.name) for f in uploaded_files]
        combined = pd.concat([st.session_state.mra_data, *new_records], ignore_index=True)
        st.session_state.mra_data = apply_early_warning(combined, auto_fix=auto_fix_enabled).drop_duplicates(subset=['MRA_ID'])

if not st.session_state.mra_data.empty:
    # 1. TOP-LEVEL ANALYTICS
    st.subheader("📊 Portfolio Risk Analytics")
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        st.metric("Master Inventory", len(st.session_state.mra_data))
        crit_count = len(st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨")])
        st.metric("Critical Alerts", crit_count, delta_color="inverse")
    
    with col2:
        # Donut Chart
        dist = st.session_state.mra_data['Risk_Status'].value_counts().reset_index()
        fig_donut = px.pie(dist, values='count', names='Risk_Status', hole=0.5, 
                           color='Risk_Status', color_discrete_map={"🚨 CRITICAL: 75%+ Elapsed": "#FF4B4B", "⚠️ WARNING: 50% Elapsed": "#FFAA00", "🟢 On Track": "#00CC96", "✅ Closed": "#2E7D32"})
        fig_donut.update_layout(showlegend=False, height=200, margin=dict(t=0, b=0, l=0, r=0))
        st.plotly_chart(fig_donut, use_container_width=True)

    with col3:
        # HEATMAP: Risk by Owner
        heatmap_data = st.session_state.mra_data.groupby(['Owner', 'Risk_Status']).size().unstack(fill_value=0)
        fig_heat = px.bar(heatmap_data, title="Concentration of Risk by Owner", barmode="stack",
                          color_discrete_map={"🚨 CRITICAL: 75%+ Elapsed": "#FF4B4B", "⚠️ WARNING: 50% Elapsed": "#FFAA00", "🟢 On Track": "#00CC96", "✅ Closed": "#2E7D32"})
        fig_heat.update_layout(height=250, margin=dict(t=30, b=0, l=0, r=0), xaxis_title=None, yaxis_title="Count")
        st.plotly_chart(fig_heat, use_container_width=True)

    # 2. INTERACTIVE LEDGER (Manual Add Enabled)
    st.subheader("📋 Centralized Remediation Ledger")
    st.caption("Instructions: Use the bottom row to **Add a Finding** manually. Select a row and press 'Delete' to **Remove** it.")
    
    edited_df = st.data_editor(
        st.session_state.mra_data,
        use_container_width=True,
        num_rows="dynamic", # Enables "Add" and "Delete"
        column_config={
            "Status": st.column_config.SelectboxColumn(options=["In Progress", "Submitted for Review", "Closed"]),
            "Deadline": st.column_config.DateColumn(),
            "Start_Date": st.column_config.DateColumn(),
            "Risk_Status": st.column_config.TextColumn(disabled=True)
        }
    )
    st.session_state.mra_data = apply_early_warning(edited_df, auto_fix=auto_fix_enabled)

    # 3. ROADMAP & EMAIL
    tab1, tab2 = st.tabs(["🗺️ Strategic Roadmap", "📧 Escalation Alerts"])
    
    with tab1:
        chart_df = st.session_state.mra_data.copy()
        chart_df = chart_df[chart_df['Start_Date'] < chart_df['Deadline']].reset_index(drop=True)
        if not chart_df.empty:
            fig_gantt = px.timeline(chart_df, start="Start_Date", end="Deadline", x_start="Start_Date", x_end="Deadline", 
                                    y="MRA_ID", color="Risk_Status", color_discrete_map={"🚨 CRITICAL: 75%+ Elapsed": "#FF4B4B", "⚠️ WARNING: 50% Elapsed": "#FFAA00", "🟢 On Track": "#00CC96", "✅ Closed": "#2E7D32"})
            fig_gantt.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_gantt, use_container_width=True)
        else:
            st.warning("Ensure valid dates to view Roadmap.")

    with tab2:
        critical_items = st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨")]
        if not critical_items.empty:
            target = st.selectbox("Select MRA for Alert:", critical_items['MRA_ID'])
            row = critical_items[critical_items['MRA_ID'] == target].iloc[0]
            st.text_area("Draft Notification", f"Subject: URGENT: Remediation Alert [{row['MRA_ID']}]\n\nDear {row['Owner']},\n\nFinding {row['MRA_ID']} is at CRITICAL risk (75%+ timeline elapsed).\nDeadline: {row['Deadline'].strftime('%Y-%m-%d')}\n\nPlease provide a status update immediately.", height=150)
        else:
            st.success("No critical alerts required.")

    st.download_button("📥 Export CSV", convert_df_to_csv(st.session_state.mra_data), "MRA_Tracker_Export.csv", "text/csv")
