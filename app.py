import streamlit as st
import pandas as pd
import plotly.express as px
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta

# --- CONFIGURATION ---
REGULATORY_MAP = {
    "OCC": {"identifier": "Comptroller", "keywords": [r"Target Date", r"Commitment Date"]},
    "FRB": {"identifier": "Federal Reserve", "keywords": [r"Timeline", r"Due Date", r"Expectation Date"]}
}

def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

# --- EXTRACTION ENGINE ---
def extract_mra_from_pdf(pdf_bytes):
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc: text += page.get_text()

    agency = "FRB" if REGULATORY_MAP["FRB"]["identifier"] in text else "OCC"
    keywords = REGULATORY_MAP[agency]["keywords"]
    date_matches = re.findall(rf"(?:{'|'.join(keywords)})[:\s]*(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})", text, re.IGNORECASE)

    extracted_findings = []
    # If no dates found, use a future date to avoid immediate "Critical" status
    default_deadline = (datetime.now() + timedelta(days=90)).replace(tzinfo=None)
    
    for i, date_str in enumerate(date_matches if date_matches else ["Placeholder"]):
        try:
            deadline = pd.to_datetime(date_str).replace(tzinfo=None)
        except:
            deadline = default_deadline

        extracted_findings.append({
            "MRA_ID": f"{agency}-2024-{i+1:03}",
            "Agency": agency,
            "Owner": "Assignee Pending",
            "Start_Date": (datetime.now() - timedelta(days=1)).replace(tzinfo=None),
            "Deadline": deadline,
            "Status": "In Progress"
        })
    return pd.DataFrame(extracted_findings)

# --- EARLY WARNING LOGIC ---
def apply_early_warning(df):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None)
    
    df['Deadline'] = pd.to_datetime(df['Deadline']).dt.tz_localize(None)
    df['Start_Date'] = pd.to_datetime(df['Start_Date']).dt.tz_localize(None)

    def calculate_risk(row):
        if row['Status'] == "Closed": return "✅ Closed"
        # Validate logic: Start must be before Deadline
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

if "mra_data" not in st.session_state:
    st.session_state.mra_data = pd.DataFrame()

uploaded_file = st.file_uploader("Upload Regulatory PDF", type=["pdf"])

if uploaded_file:
    if st.button("Analyze PDF") or st.session_state.mra_data.empty:
        st.session_state.mra_data = apply_early_warning(extract_mra_from_pdf(uploaded_file.read()))

if not st.session_state.mra_data.empty:
    st.subheader("Interactive Remediation Ledger")
    
    # Editable table
    edited_df = st.data_editor(
        st.session_state.mra_data,
        column_config={
            "Status": st.column_config.SelectboxColumn(options=["In Progress", "Submitted for Review", "Closed"]),
            "Deadline": st.column_config.DateColumn(required=True),
            "Start_Date": st.column_config.DateColumn(required=True)
        },
        use_container_width=True, num_rows="dynamic", key="mra_editor"
    )
    
    st.session_state.mra_data = apply_early_warning(edited_df)

    # --- THE GANTT CHART (With Chronology Guard) ---
    st.subheader("Remediation Roadmap")
    chart_df = st.session_state.mra_data.copy()
    
    # 1. Standardize types and strip timezones
    chart_df['Deadline'] = pd.to_datetime(chart_df['Deadline']).dt.tz_localize(None)
    chart_df['Start_Date'] = pd.to_datetime(chart_df['Start_Date']).dt.tz_localize(None)
    
    # 2. CHRONOLOGY GUARD: Drop rows where Start is after Deadline
    chart_df = chart_df[chart_df['Start_Date'] < chart_df['Deadline']]
    chart_df = chart_df.reset_index(drop=True)

    if not chart_df.empty:
        fig = px.timeline(
            chart_df, 
            start="Start_Date", end="Deadline", 
            x_start="Start_Date", x_end="Deadline", 
            y="MRA_ID", color="Risk_Status",
            color_discrete_map={
                "🚨 CRITICAL: 75%+ Elapsed": "#FF4B4B",
                "⚠️ WARNING: 50% Elapsed": "#FFAA00",
                "🟢 On Track": "#00CC96",
                "✅ Closed": "#2E7D32"
            }
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("⚠️ Roadmap hidden: Check your dates. The **Start Date** must be earlier than the **Deadline**.")

    st.download_button("📥 Export Ledger to CSV", convert_df_to_csv(st.session_state.mra_data), "MRA_Sentinel_Export.csv", "text/csv")
