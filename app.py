import streamlit as st
import pandas as pd
import plotly.express as px
import re
from datetime import datetime, timedelta

# --- 1. EXTRACTION LOGIC (The NLP "Sentinel") ---
def extract_mra_from_text(text):
    """
    Scans text for MRA indicators. In a real app, use PyMuPDF to 
    read PDF bytes and spaCy for deeper entity extraction.
    """
    # Mock regex to find common agency patterns (e.g., 'Target Date: 12/31/2024')
    date_pattern = r"(?:Target|Completion|Due)\s*Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})"
    dates = re.findall(date_pattern, text)
    
    # Mock data structure to simulate extraction from OCC/FRB letters
    # In production, this would parse the specific 'Five Cs' or 'Required Actions'
    data = [{
        "MRA_ID": "MRA-2024-OCC-01",
        "Finding": "Inadequate Model Risk Validation",
        "Owner": "Director of Quantitative Analytics",
        "Start_Date": datetime.now() - timedelta(days=20),
        "Deadline": datetime.strptime(dates[0], "%m/%d/%Y") if dates else datetime.now() + timedelta(days=90),
        "Status": "In Progress"
    }]
    return pd.DataFrame(data)

# --- 2. EARLY WARNING SYSTEM (EWS) LOGIC ---
def apply_early_warning(df):
    today = datetime.now()
    
    def calculate_risk(row):
        total_duration = (row['Deadline'] - row['Start_Date']).days
        elapsed = (today - row['Start_Date']).days
        
        # Avoid division by zero
        burn_rate = elapsed / total_duration if total_duration > 0 else 0
        
        if row['Status'] == "Closed":
            return "✅ Closed"
        if burn_rate >= 0.75:
            return "🚨 CRITICAL: 75% Time Elapsed"
        if burn_rate >= 0.50:
            return "⚠️ WARNING: 50% Time Elapsed"
        return "🟢 On Track"

    df['Risk_Status'] = df.apply(calculate_risk, axis=1)
    return df

# --- 3. STREAMLIT COMMAND CENTER UI ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")

st.title("🛡️ MRA Sentinel: Regulatory Command Center")
st.markdown("### NLP-Driven Remediation & Early Warning System")

uploaded_file = st.file_uploader("Upload Regulatory Exam Letter (OCC/FRB)", type=["txt", "pdf"])

# Sidebar for manual controls/overrides
st.sidebar.header("Sentinel Settings")
threshold = st.sidebar.slider("Early Warning Threshold (%)", 50, 90, 75)

if uploaded_file:
    # Simulated Text Extraction (Assuming text for this MVP)
    raw_text = uploaded_file.getvalue().decode("utf-8")
    
    with st.spinner("Analyzing letter for findings..."):
        df = extract_mra_from_text(raw_text)
        df = apply_early_warning(df)

    # Metric Row
    col1, col2, col3 = st.columns(3)
    col1.metric("Total MRAs", len(df))
    col2.metric("At Risk (>75%)", len(df[df['Risk_Status'].str.contains("🚨")]))
    col3.metric("Remediation Health", "Fair")

    # Gantt Chart
    st.subheader("Remediation Timeline & Early Warning Flags")
    fig = px.timeline(
        df, 
        start="Start_Date", 
        end="Deadline", 
        x_start="Start_Date", 
        x_end="Deadline", 
        y="MRA_ID", 
        color="Risk_Status",
        color_discrete_map={
            "🚨 CRITICAL: 75% Time Elapsed": "#EF553B",
            "⚠️ WARNING: 50% Time Elapsed": "#FECB52",
            "🟢 On Track": "#00CC96"
        },
        hover_data=["Owner", "Finding"]
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

    # Data Table
    st.subheader("Extracted Finding Details")
    st.dataframe(df, use_container_width=True)
else:
    st.info("Please upload an exam letter to begin the auto-mapping process.")
