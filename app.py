import streamlit as st
import pandas as pd
import plotly.express as px
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta

# --- CONFIGURATION ---
REGULATORY_MAP = {
    "OCC": {
        "headers": [r"Concern", r"Cause", r"Consequence", r"Corrective Action", r"Commitment"],
        "deadline_keywords": [r"Target Date", r"Commitment Date", r"Completion Date"],
        "identifier": "Comptroller"
    },
    "FRB": {
        "headers": [r"Matter Requiring Attention", r"Matter Requiring Immediate Attention", r"Required Action"],
        "deadline_keywords": [r"Timeline", r"Due Date", r"Expectation Date"],
        "identifier": "Federal Reserve"
    }
}

def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

# --- EXTRACTION ENGINE ---
def extract_mra_from_pdf(pdf_bytes):
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()

    agency = "FRB" if REGULATORY_MAP["FRB"]["identifier"] in text else "OCC"
    config = REGULATORY_MAP[agency]
    deadline_pattern = "|".join(config["deadline_keywords"])
    date_matches = re.findall(rf"(?:{deadline_pattern})[:\s]*(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})", text, re.IGNORECASE)

    extracted_findings = []
    for i, date_str in enumerate(date_matches):
        try:
            # Force naive datetime
            deadline = pd.to_datetime(date_str).replace(tzinfo=None)
        except:
            deadline = datetime.now().replace(tzinfo=None) + timedelta(days=90)

        extracted_findings.append({
            "MRA_ID": f"{agency}-2024-{i+1:03}",
            "Agency": agency,
            "Owner": "Assignee Pending",
            "Start_Date": datetime.now().replace(tzinfo=None) - timedelta(days=10),
            "Deadline": deadline,
            "Status": "In Progress"
        })
    return pd.DataFrame(extracted_findings), text

# --- EARLY WARNING LOGIC ---
def apply_early_warning(df):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None)
    
    def calculate_risk(row):
        if row['Status'] == "Closed": return "✅ Closed"
        # Ensure comparison is naive
        deadline = pd.to_datetime(row['Deadline']).replace(tzinfo=None)
        start = pd.to_datetime(row['Start_Date']).replace(tzinfo=None)
        
        total_window = (deadline - start).days
        elapsed = (today - start).days
        burn_rate = elapsed / total_window if total_window > 0 else 1
        
        if burn_rate >= 0.75: return "🚨 CRITICAL: 75%+ Elapsed"
        if burn_rate >= 0.50: return "⚠️ WARNING: 50% Elapsed"
        return "🟢 On Track"

    df['Risk_Status'] = df.apply(calculate_risk, axis=1)
    return df

# --- UI SETUP ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")
st.title("🛡️ MRA Sentinel: Command Center")

# Use session state to persist edits
if "mra_data" not in st.session_state:
    st.session_state.mra_data = pd.DataFrame()

uploaded_file = st.file_uploader("Upload Regulatory PDF", type=["pdf"])

if uploaded_file:
    if st.button("Re-Scan PDF") or st.session_state.mra_data.empty:
        raw_df, _ = extract_mra_from_pdf(uploaded_file.read())
        st.session_state.mra_data = apply_early_warning(raw_df)

if not st.session_state.mra_data.empty:
    # 1. EDITABLE TABLE
    st.subheader("Interactive Remediation Ledger")
    st.info("Edit the **Owner**, **Deadline**, or **Status** below. The chart will update automatically.")
    
    # Enable editing
    edited_df = st.data_editor(
        st.session_state.mra_data,
        column_config={
            "Status": st.column_config.SelectboxColumn(options=["In Progress", "Submitted for Review", "Closed"]),
            "Deadline": st.column_config.DateColumn(),
            "Start_Date": st.column_config.DateColumn()
        },
        use_container_width=True,
        num_rows="dynamic"
    )
    
    # Re-apply risk logic to edited data
    st.session_state.mra_data = apply_early_warning(edited_df)

    # 2. GANTT CHART (Hardened)
    st.subheader("Remediation Roadmap")
    chart_df = st.session_state.mra_data.copy()
    # Force conversion to naive datetime for Plotly
    chart_df['Deadline'] = pd.to_datetime(chart_df['Deadline']).dt.tz_localize(None)
    chart_df['Start_Date'] = pd.to_datetime(chart_df['Start_Date']).dt.tz_localize(None)

    fig = px.timeline(
        chart_df, 
        start="Start_Date", 
        end="Deadline", 
        x_start="Start_Date", 
        x_end="Deadline", 
        y="MRA_ID", 
        color="Risk_Status",
        color_discrete_map={
            "🚨 CRITICAL: 75%+ Elapsed": "#FF4B4B",
            "⚠️ WARNING: 50% Elapsed": "#FFAA00",
            "🟢 On Track": "#00CC96",
            "✅ Closed": "#2E7D32"
        },
        hover_data=["Owner", "Status"]
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

    # 3. DOWNLOAD
    st.download_button(
        label="📥 Export Final Ledger to CSV",
        data=convert_df_to_csv(st.session_state.mra_data),
        file_name=f"MRA_Sentinel_Export_{datetime.now().strftime('%Y%m%d')}.csv",
        mime='text/csv'
    )
