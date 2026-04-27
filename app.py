import streamlit as st
import pandas as pd
import plotly.express as px
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta
import io

# --- NLP & EXTRACTION LOGIC ---
def extract_mra_from_pdf(pdf_bytes):
    """
    Parses PDF bytes, extracts text, and maps findings to owners/deadlines.
    """
    text = ""
    # Open the PDF from memory
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()

    # 1. Look for Agency-Specific Patterns
    is_occ = any(term in text.upper() for term in ["OCC", "COMPTROLLER"])
    is_frb = any(term in text.upper() for term in ["FRB", "FEDERAL RESERVE"])

    # 2. Heuristic: Find Dates (e.g., 12/31/2024 or Dec 31, 2024)
    date_pattern = r"(\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b)"
    found_dates = re.findall(date_pattern, text)
    
    # 3. Heuristic: Identify Findings (Simplified for MVP)
    # Looks for "MRA #X" or "Finding X"
    finding_titles = re.findall(r"(MRA\s*#?\s*\d+|Matter\s*Requiring\s*Attention\s*\d*)", text, re.IGNORECASE)
    
    # Construct Mock Data based on extraction
    # In a full build, you'd map the text between findings to specific owners via spaCy
    extracted_data = []
    for i, title in enumerate(finding_titles[:3]):  # Limit to first 3 for demo
        deadline = datetime.now() + timedelta(days=90)
        if len(found_dates) > i:
            try: deadline = pd.to_datetime(found_dates[i])
            except: pass
            
        extracted_data.append({
            "MRA_ID": title if title else f"MRA-2024-{i+1}",
            "Agency": "OCC" if is_occ else "FRB" if is_frb else "Unknown",
            "Owner": "Line of Business Lead" if i % 2 == 0 else "Risk/Compliance Officer",
            "Start_Date": datetime.now() - timedelta(days=15),
            "Deadline": deadline,
            "Status": "In Progress"
        })

    return pd.DataFrame(extracted_data), text

# --- EARLY WARNING LOGIC ---
def apply_early_warning(df):
    today = datetime.now()
    def calculate_risk(row):
        if row['Status'] == "Closed": return "✅ Closed"
        total_days = (row['Deadline'] - row['Start_Date']).days
        elapsed = (today - row['Start_Date']).days
        burn = elapsed / total_days if total_days > 0 else 1
        
        if burn >= 0.75: return "🚨 CRITICAL: 75%+ Elapsed"
        if burn >= 0.50: return "⚠️ WARNING: 50%+ Elapsed"
        return "🟢 On Track"
    
    df['Risk_Status'] = df.apply(calculate_risk, axis=1)
    return df

# --- STREAMLIT UI ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")
st.title("🛡️ MRA Sentinel: Command Center")

uploaded_file = st.file_uploader("Upload Regulatory PDF (OCC/FRB)", type=["pdf"])

if uploaded_file:
    df, full_text = extract_mra_from_pdf(uploaded_file.read())
    df = apply_early_warning(df)

    # Dashboard Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Findings Detected", len(df))
    m2.metric("High Risk Items", len(df[df['Risk_Status'].str.contains("🚨")]))
    m3.metric("Avg. Time to Deadline", f"{(df['Deadline'] - datetime.now()).mean().days} Days")

    # Gantt Visualization
    st.subheader("Remediation Tracker")
    fig = px.timeline(df, start="Start_Date", end="Deadline", x_start="Start_Date", x_end="Deadline", 
                      y="MRA_ID", color="Risk_Status", 
                      color_discrete_map={"🚨 CRITICAL: 75%+ Elapsed": "#FF4B4B", "⚠️ WARNING: 50%+ Elapsed": "#FFAA00", "🟢 On Track": "#00CC96"},
                      hover_data=["Owner", "Agency"])
    st.plotly_chart(fig, use_container_width=True)

    # Detailed Table & Raw Text
    tab1, tab2 = st.tabs(["Mapped Findings", "Raw Extraction"])
    with tab1:
        st.dataframe(df, use_container_width=True)
    with tab2:
        st.text_area("Extracted OCR Text", full_text, height=300)
else:
    st.info("Upload a regulatory letter to auto-populate the tracker.")
