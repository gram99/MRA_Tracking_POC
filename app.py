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

THEME_REFS = {
    "Cybersecurity/IT": {"keywords": [r"cyber", r"it risk"], "ref": "OCC 2013-29"},
    "Financial Crime/AML": {"keywords": [r"aml", r"bsa"], "ref": "FFIEC BSA/AML"},
    "Model Risk": {"keywords": [r"model risk", r"validation"], "ref": "SR 11-7"},
    "Compliance/Legal": {"keywords": [r"compliance", r"legal"], "ref": "OCC 2014-52"},
    "Capital/Liquidity": {"keywords": [r"capital", r"liquidity"], "ref": "Reg YY"}
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

    identified_theme = "General / Other"
    suggested_ref = "N/A"
    for theme, config in THEME_REFS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in config["keywords"]):
            identified_theme = theme
            suggested_ref = config["ref"]
            break

    extracted_findings = []
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    
    for i, date_str in enumerate(date_matches if date_matches else ["Manual Entry"]):
        try:
            deadline = pd.to_datetime(date_str).to_pydatetime().replace(tzinfo=None)
        except:
            deadline = today + timedelta(days=90)

        extracted_findings.append({
            "MRA_ID": f"{agency}-{filename[:5].upper()}-{i+1:02}",
            "Theme": identified_theme,
            "Reg_Reference": suggested_ref,
            "Owner": "LOB Pending",
            "Start_Date": today - timedelta(days=30),
            "Deadline": deadline,
            "Status": "In Progress",
            "Last_Updated": today,
            "Days_Since_Update": 0
        })
    return pd.DataFrame(extracted_findings)

# --- SENTINEL LOGIC ---
def apply_sentinel_logic(df):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    
    # Initialize columns if they were created via manual 'Add Row'
    cols = ["Deadline", "Start_Date", "Last_Updated", "Days_Since_Update", "Status", "Theme", "Reg_Reference"]
    for c in cols:
        if c not in df.columns: df[c] = None

    # Cast dates
    df['Deadline'] = pd.to_datetime(df['Deadline'], errors='coerce').dt.tz_localize(None)
    df['Start_Date'] = pd.to_datetime(df['Start_Date'], errors='coerce').dt.tz_localize(None)
    df['Last_Updated'] = pd.to_datetime(df['Last_Updated'], errors='coerce').dt.tz_localize(None).fillna(today)

    def process_row(row):
        # 1. Stale Check
        days_stale = (today - row['Last_Updated']).days
        row['Days_Since_Update'] = max(0, days_stale)
        stale_prefix = "🧊 STALE: " if days_stale > 30 and row['Status'] != "Closed" else ""

        # 2. Risk Math
        if pd.isnull(row['Deadline']) or pd.isnull(row['Start_Date']):
            row['Risk_Status'] = "⚠️ Missing Dates"
            row['Days_Remaining'] = 0
            return row
            
        delta = (row['Deadline'] - today).days
        row['Days_Remaining'] = delta if row['Status'] != "Closed" else 0
        
        if row['Status'] == "Closed": row['Risk_Status'] = "✅ Closed"
        elif delta < 0: row['Risk_Status'] = f"{stale_prefix}💀 OVERDUE"
        elif row['Start_Date'] >= row['Deadline']: row['Risk_Status'] = "⚠️ Date Inversion"
        else:
            window = (row['Deadline'] - row['Start_Date']).days
            elapsed = (today - row['Start_Date']).days
            burn = elapsed / window if window > 0 else 1
            if burn >= 0.75: row['Risk_Status'] = f"{stale_prefix}🚨 CRITICAL: 75%+"
            elif burn >= 0.50: row['Risk_Status'] = f"{stale_prefix}⚠️ WARNING: 50%+"
            else: row['Risk_Status'] = f"{stale_prefix}🟢 On Track"
        return row

    return df.apply(process_row, axis=1)

# --- UI SETUP ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")
st.title("🛡️ MRA Sentinel: Command Center")

if "mra_data" not in st.session_state: st.session_state.mra_data = pd.DataFrame()
if "audit_log" not in st.session_state: st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Prev", "New", "Audit_Context"])
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0

# Sidebar
st.sidebar.header("Sentinel Controls")
if st.sidebar.button("📁 Clear Files"):
    st.session_state.uploader_key += 1
    st.rerun()
if st.sidebar.button("🗑️ Reset Tracker"):
    st.session_state.mra_data = pd.DataFrame()
    st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Prev", "New", "Audit_Context"])
    st.rerun()

uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True, key=f"up_{st.session_state.uploader_key}")
if uploaded_files:
    if st.button("🚀 Ingest Findings"):
        new_recs = [extract_mras_from_pdf(f.read(), f.name) for f in uploaded_files]
        combined = pd.concat([st.session_state.mra_data, *new_recs], ignore_index=True)
        st.session_state.mra_data = apply_sentinel_logic(combined).drop_duplicates(subset=['MRA_ID'])

if not st.session_state.mra_data.empty:
    tab_exec, tab_ledger, tab_roadmap, tab_alerts, tab_audit = st.tabs(["📊 Executive Dashboard", "📋 Centralized Ledger", "🗺️ Strategic Roadmap", "📧 Alerts", "📜 Audit Trail"])

    with tab_exec:
        st.subheader("Portfolio Risk Snapshot")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total MRAs", len(st.session_state.mra_data))
            risk_c = len(st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀")])
            st.metric("Risk Portfolio", risk_c, delta_color="inverse")
        with col2:
            chart_df = st.session_state.mra_data.copy()
            # Clean Risk_Status for chart domain consistency
            chart_df['Simple_Risk'] = chart_df['Risk_Status'].str.replace("🧊 STALE: ", "")
            exec_chart = alt.Chart(chart_df).mark_bar().encode(
                x='count():Q', y=alt.Y('Simple_Risk:N', sort='-x', title=None),
                color=alt.Color('Simple_Risk:N', scale=alt.Scale(domain=["💀 OVERDUE", "🚨 CRITICAL: 75%+", "⚠️ WARNING: 50%+", "🟢 On Track", "✅ Closed"], range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"]))
            ).properties(height=200)
            st.altair_chart(exec_chart, use_container_width=True)

    with tab_ledger:
        st.subheader("Interactive Remediation Ledger")
        old_df = st.session_state.mra_data.copy()
        edited_df = st.data_editor(st.session_state.mra_data, use_container_width=True, num_rows="dynamic", key="led_edit",
                                   column_config={"Theme": st.column_config.SelectboxColumn(options=list(THEME_REFS.keys()) + ["General / Other"]),
                                                  "Days_Since_Update": st.column_config.NumberColumn("Age (Days)", disabled=True)})
        if not edited_df.equals(old_df):
            today = datetime.now().replace(tzinfo=None)
            for idx, row in edited_df.iterrows():
                if idx in old_df.index and row['Status'] != old_df.loc[idx, 'Status']:
                    edited_df.at[idx, 'Last_Updated'] = today
                    over_days = (today - pd.to_datetime(row['Deadline']).replace(tzinfo=None)).days
                    ctx = f"⚠️ Post-Deadline ({over_days}d late)" if over_days > 0 else "✅ On-Schedule"
                    new_log = pd.DataFrame([{"Timestamp": today.strftime("%Y-%m-%d %H:%M:%S"), "MRA_ID": row['MRA_ID'], "Event": "Status Change", "Prev": old_df.loc[idx, 'Status'], "New": row['Status'], "Audit_Context": ctx}])
                    st.session_state.audit_log = pd.concat([st.session_state.audit_log, new_log], ignore_index=True)
            st.session_state.mra_data = apply_sentinel_logic(edited_df)

    with tab_roadmap:
        st.subheader("Chronological Roadmap")
        # --- HARDENING: Remove STALE prefix for chart rendering consistency ---
        roadmap_df = st.session_state.mra_data.copy()
        roadmap_df['Chart_Risk'] = roadmap_df['Risk_Status'].str.replace("🧊 STALE: ", "")
        roadmap_df = roadmap_df.dropna(subset=['Start_Date', 'Deadline'])
        
        if not roadmap_df.empty:
            gantt = alt.Chart(roadmap_df).mark_bar().encode(
                x=alt.X('Start_Date:T', title='Timeline'),
                x2='Deadline:T',
                y=alt.Y('MRA_ID:N', sort='ascending', title=None),
                color=alt.Color('Chart_Risk:N', scale=alt.Scale(domain=["💀 OVERDUE", "🚨 CRITICAL: 75%+", "⚠️ WARNING: 50%+", "🟢 On Track", "✅ Closed"], range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"])),
                tooltip=['MRA_ID', 'Theme', 'Owner', 'Status', 'Days_Since_Update']
            ).properties(height=alt.Step(40)).interactive()
            st.altair_chart(gantt, use_container_width=True)
        else:
            st.info("Assign dates in the Ledger to view the Roadmap.")

    with tab_alerts:
        critical = st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀|🧊")]
        if not critical.empty:
            target = st.selectbox("Select MRA for Alert:", critical['MRA_ID'])
            row = critical[critical['MRA_ID'] == target].iloc[0]
            email = f"Subject: URGENT: {row['MRA_ID']} Alert\n\nDear {row['Owner']},\n\nFinding {row['MRA_ID']} is flagged as {row['Risk_Status']}.\nDeadline: {row['Deadline'].strftime('%Y-%m-%d')}\nDays Since Last Update: {int(row['Days_Since_Update'])}\n\nPlease update status immediately."
            st.text_area("Draft Notification", email, height=180)

    with tab_audit:
        st.dataframe(st.session_state.audit_log, use_container_width=True)
        st.download_button("📥 Export Audit Log", convert_df_to_csv(st.session_state.audit_log), "MRA_Audit.csv", "text/csv")

    st.download_button("📥 Export Master Tracker", convert_df_to_csv(st.session_state.mra_data), "MRA_Master_Tracker.csv", "text/csv")
