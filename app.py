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
    # If no dates found, create one dummy finding so the app doesn't stay empty
    if not date_matches:
        date_matches = [(datetime.now() + timedelta(days=90)).strftime("%m/%d/%Y")]

    for i, date_str in enumerate(date_matches):
        try:
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
    
    # Ensure dates are datetime objects before math
    df['Deadline'] = pd.to_datetime(df['Deadline']).dt.tz_localize(None)
    df['Start_Date'] = pd.to_datetime(df['Start_Date']).dt.tz_localize(None)

    def calculate_risk(row):
        if row['Status'] == "Closed": return "✅ Closed"
        
        # Guard against NaT (Not a Time)
        if pd.isnull(row['Deadline']) or pd.isnull(row['Start_Date']):
            return "⚪ Missing Dates"

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

if "mra_data" not in st.session_state:
    st.session_state.mra_data = pd.DataFrame()

uploaded_file = st.file_uploader("Upload Regulatory PDF", type=["pdf"])

if uploaded_file:
    if st.button("Analyze PDF") or st.session_state.mra_data.empty:
        raw_df, _ = extract_mra_from_pdf(uploaded_file.read())
        st.session_state.mra_data = apply_early_warning(raw_df)

if not st.session_state.mra_data.empty:
    st.subheader("Interactive Remediation Ledger")
    
    # Enable editing
    edited_df = st.data_editor(
        st.session_state.mra_data,
        column_config={
            "Status": st.column_config.SelectboxColumn(options=["In Progress", "Submitted for Review", "Closed"]),
            "Deadline": st.column_config.DateColumn(required=True),
            "Start_Date": st.column_config.DateColumn(required=True)
        },
        use_container_width=True,
        num_rows="dynamic",
        key="editor"
    )
    
    # Re-apply risk logic to edited data
    st.session_state.mra_data = apply_early_warning(edited_df)

    # 2. GANTT CHART (Hardened against nulls)
    st.subheader("Remediation Roadmap")
    
    # Final data cleaning for Plotly
    chart_df = st.session_state.mra_data.copy()
    chart_df['Deadline'] = pd.to_datetime(chart_df['Deadline'], errors='coerce')
    chart_df['Start_Date'] = pd.to_datetime(chart_df['Start_Date'], errors='coerce')
    
    # CRITICAL: Drop any row that doesn't have a valid Start and End date
    chart_df = chart_df.dropna(subset=['Start_Date', 'Deadline'])

    if not chart_df.empty:
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
                "✅ Closed": "#2E7D32",
                "⚪ Missing Dates": "#808080"
            },
            hover_data=["Owner", "Status"]
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Please ensure all rows have valid 'Start_Date' and 'Deadline' to view the roadmap.")

    st.download_button(
        label="📥 Export Final Ledger to CSV",
        data=convert_df_to_csv(st.session_state.mra_data),
        file_name=f"MRA_Sentinel_Export.csv",
        mime='text/csv'
    )
