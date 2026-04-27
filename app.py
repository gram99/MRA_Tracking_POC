import streamlit as st
import pandas as pd
import plotly.express as px
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta

# --- CONFIGURATION & REGEX DICTIONARY ---
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

# --- LOGIC: EXTRACTION ENGINE ---
def extract_mra_from_pdf(pdf_bytes):
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()

    # Determine Agency
    agency = "FRB" if REGULATORY_MAP["FRB"]["identifier"] in text else "OCC"
    config = REGULATORY_MAP[agency]

    # NLP Logic: Find deadlines based on agency-specific keywords
    deadline_pattern = "|".join(config["deadline_keywords"])
    # Regex looks for the keyword, optional punctuation, and a date (MM/DD/YYYY)
    date_matches = re.findall(rf"(?:{deadline_pattern})[:\s]*(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})", text, re.IGNORECASE)

    extracted_findings = []
    for i, date_str in enumerate(date_matches):
        try:
            deadline = pd.to_datetime(date_str)
        except:
            deadline = datetime.now() + timedelta(days=90)

        extracted_findings.append({
            "MRA_ID": f"{agency}-2024-{i+1:03}",
            "Agency": agency,
            "Finding_Summary": f"Extracted from {agency} Letter",
            "Owner": "Assignee Pending",
            "Start_Date": datetime.now() - timedelta(days=10),
            "Deadline": deadline,
            "Status": "In Progress"
        })

    if not extracted_findings: # Fallback for empty/unstructured text
        return pd.DataFrame(), text
        
    return pd.DataFrame(extracted_findings), text

# --- LOGIC: EARLY WARNING SYSTEM (EWS) ---
def apply_early_warning(df):
    if df.empty: return df
    today = datetime.now()
    
    def calculate_risk(row):
        total_window = (row['Deadline'] - row['Start_Date']).days
        elapsed = (today - row['Start_Date']).days
        burn_rate = elapsed / total_window if total_window > 0 else 1
        
        if burn_rate >= 0.75: return "🚨 CRITICAL: 75%+ Time Elapsed"
        if burn_rate >= 0.50: return "⚠️ WARNING: 50% Time Elapsed"
        return "🟢 On Track"

    df['Risk_Status'] = df.apply(calculate_risk, axis=1)
    return df

# --- STREAMLIT DASHBOARD UI ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")

st.title("🛡️ MRA Sentinel: Command Center")
st.markdown("### Automated Regulatory Ingestion & Early Warning Tracker")

# Sidebar
st.sidebar.header("Sentinel Controls")
st.sidebar.info("This system uses Custom Regex Mapping for OCC & FRB exam letters.")

uploaded_file = st.file_uploader("Upload Regulatory PDF (OCC or FRB)", type=["pdf"])

if uploaded_file:
    # Processing
    with st.spinner("Executing Sentinel Scan..."):
        df, raw_text = extract_mra_from_pdf(uploaded_file.read())
        df = apply_early_warning(df)

    if not df.empty:
        # Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Findings Identified", len(df))
        m2.metric("High Risk (EWS)", len(df[df['Risk_Status'].str.contains("🚨")]))
        m3.metric("Detected Agency", df['Agency'].iloc[0])

        # Gantt Visualization
        st.subheader("Remediation Roadmap")
        fig = px.timeline(
            df, 
            start="Start_Date", 
            end="Deadline", 
            x_start="Start_Date", 
            x_end="Deadline", 
            y="MRA_ID", 
            color="Risk_Status",
            color_discrete_map={
                "🚨 CRITICAL: 75%+ Time Elapsed": "#FF4B4B",
                "⚠️ WARNING: 50% Time Elapsed": "#FFAA00",
                "🟢 On Track": "#00CC96"
            },
            hover_data=["Owner", "Deadline"]
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

        # Data View
        st.subheader("Detailed Remediation Ledger")
        st.dataframe(df, use_container_width=True)
    else:
        st.error("Sentinel could not identify specific MRA patterns. Check the 'Raw Text' tab.")
        with st.expander("View Raw Text"):
            st.text(raw_text)
else:
    st.info("Awaiting PDF upload to initialize Command Center.")
