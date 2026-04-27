import streamlit as st
import pandas as pd
import altair as alt
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta

# --- CONFIGURATION ---
REGULATORY_MAP = {
    "OCC": {"identifier": "Comptroller", "keywords": [r"Target Date", r"Commitment Date"]},
    "FRB": {"identifier": "Federal Reserve", "keywords": [r"Timeline", r"Due Date"]}
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
    today_naive = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    
    for i, date_str in enumerate(date_matches if date_matches else ["Manual Entry"]):
        try:
            deadline = pd.to_datetime(date_str).to_pydatetime().replace(tzinfo=None)
        except:
            deadline = today_naive + timedelta(days=90)

        extracted_findings.append({
            "MRA_ID": f"{agency}-{filename[:5].upper()}-{i+1:02}",
            "Owner": "LOB Pending",
            "Start_Date": today_naive - timedelta(days=30),
            "Deadline": deadline,
            "Status": "In Progress"
        })
    return pd.DataFrame(extracted_findings)

# --- SENTINEL LOGIC ---
def apply_sentinel_logic(df):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    
    df['Deadline'] = pd.to_datetime(df['Deadline']).dt.tz_localize(None)
    df['Start_Date'] = pd.to_datetime(df['Start_Date']).dt.tz_localize(None)

    def process_row(row):
        delta = (row['Deadline'] - today).days
        row['Days_Remaining'] = delta if row['Status'] != "Closed" else 0
        
        if row['Status'] == "Closed": 
            row['Risk_Status'] = "✅ Closed"
        elif delta < 0:
            row['Risk_Status'] = "💀 OVERDUE"
        elif row['Start_Date'] >= row['Deadline']:
            row['Risk_Status'] = "⚠️ Date Inversion"
        else:
            total_window = (row['Deadline'] - row['Start_Date']).days
            elapsed = (today - row['Start_Date']).days
            burn_rate = elapsed / total_window if total_window > 0 else 1
            if burn_rate >= 0.75: row['Risk_Status'] = "🚨 CRITICAL: 75%+"
            elif burn_rate >= 0.50: row['Risk_Status'] = "⚠️ WARNING: 50%+"
            else: row['Risk_Status'] = "🟢 On Track"
        return row

    return df.apply(process_row, axis=1)

# --- UI SETUP ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")
st.title("🛡️ MRA Sentinel: Command Center")

if "mra_data" not in st.session_state:
    st.session_state.mra_data = pd.DataFrame()

if st.sidebar.button("🗑️ Clear Tracker"):
    st.session_state.mra_data = pd.DataFrame()
    st.rerun()

uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
if uploaded_files:
    if st.button("🚀 Ingest Findings"):
        new_recs = [extract_mras_from_pdf(f.read(), f.name) for f in uploaded_files]
        combined = pd.concat([st.session_state.mra_data, *new_recs], ignore_index=True)
        st.session_state.mra_data = apply_sentinel_logic(combined).drop_duplicates(subset=['MRA_ID'])

if not st.session_state.mra_data.empty:
    # 1. ANALYTICS
    st.subheader("📊 Portfolio Risk Analytics")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("Master Inventory", len(st.session_state.mra_data))
        risk_c = len(st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀")])
        st.metric("Risk Portfolio", risk_c, delta_color="inverse")
    
    with col2:
        # Altair Heatmap/Bar for Risk by Owner
        heat_chart = alt.Chart(st.session_state.mra_data).mark_bar().encode(
            x=alt.X('count():Q', title='Count'),
            y=alt.Y('Owner:N', title=None),
            color=alt.Color('Risk_Status:N', scale=alt.Scale(
                domain=["💀 OVERDUE", "🚨 CRITICAL: 75%+", "⚠️ WARNING: 50%+", "🟢 On Track", "✅ Closed"],
                range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"]
            ))
        ).properties(height=200)
        st.altair_chart(heat_chart, use_container_width=True)

    # 2. LEDGER
    st.subheader("📋 Centralized Remediation Ledger")
    edited_df = st.data_editor(st.session_state.mra_data, use_container_width=True, num_rows="dynamic")
    st.session_state.mra_data = apply_sentinel_logic(edited_df)

    # 3. ROADMAP (Altair Gantt)
    st.subheader("🗺️ Strategic Roadmap")
    chart_df = st.session_state.mra_data.copy()
    
    # Altair is more flexible, but we still want unique Y-axis labels
    if not chart_df.empty:
        gantt = alt.Chart(chart_df).mark_bar().encode(
            x=alt.X('Start_Date:T', title='Timeline'),
            x2='Deadline:T',
            y=alt.Y('MRA_ID:N', sort='ascending', title=None),
            color=alt.Color('Risk_Status:N', scale=alt.Scale(
                domain=["💀 OVERDUE", "🚨 CRITICAL: 75%+", "⚠️ WARNING: 50%+", "🟢 On Track", "✅ Closed"],
                range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"]
            )),
            tooltip=['MRA_ID', 'Owner', 'Status', 'Days_Remaining']
        ).properties(height=alt.Step(40)).interactive()
        
        st.altair_chart(gantt, use_container_width=True)

    st.download_button("📥 Export CSV", convert_df_to_csv(st.session_state.mra_data), "MRA_Sentinel_Export.csv", "text/csv")
