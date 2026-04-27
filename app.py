import streamlit as st
import pandas as pd
import altair as alt
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta

# --- CONFIGURATION & AUTO-SEARCH MAPPING ---
REGULATORY_MAP = {
    "OCC": {"identifier": "Comptroller", "keywords": [r"Target Date", r"Commitment Date"]},
    "FRB": {"identifier": "Federal Reserve", "keywords": [r"Timeline", r"Due Date"]}
}

THEME_REFS = {
    "Cybersecurity/IT": {
        "keywords": [r"cyber", r"it risk", r"firewall", r"access control"],
        "ref": "OCC Bulletin 2013-29 / OCC 2023-17"
    },
    "Financial Crime/AML": {
        "keywords": [r"aml", r"bsa", r"money laundering", r"kyc"],
        "ref": "FFIEC BSA/AML Handbook"
    },
    "Model Risk": {
        "keywords": [r"model risk", r"validation", r"back-test", r"sr 11-7"],
        "ref": "SR 11-7 / OCC 2011-12"
    },
    "Compliance/Legal": {
        "keywords": [r"compliance", r"legal", r"regulation"],
        "ref": "OCC Bulletin 2014-52"
    },
    "Capital/Liquidity": {
        "keywords": [r"capital", r"liquidity", r"stress test"],
        "ref": "Reg YY / SR 12-7"
    }
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
    today_naive = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    
    for i, date_str in enumerate(date_matches if date_matches else ["Manual Entry"]):
        try:
            deadline = pd.to_datetime(date_str).to_pydatetime().replace(tzinfo=None)
        except:
            deadline = today_naive + timedelta(days=90)

        extracted_findings.append({
            "MRA_ID": f"{agency}-{filename[:5].upper()}-{i+1:02}",
            "Theme": identified_theme,
            "Reg_Reference": suggested_ref,
            "Owner": "LOB Pending",
            "Start_Date": today_naive - timedelta(days=30),
            "Deadline": deadline,
            "Status": "In Progress",
            "Last_Updated": today_naive # Initialize Last Updated
        })
    return pd.DataFrame(extracted_findings)

# --- SENTINEL LOGIC ---
def apply_sentinel_logic(df):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    
    for col in ["Deadline", "Start_Date", "Last_Updated"]:
        df[col] = pd.to_datetime(df[col], errors='coerce').dt.tz_localize(None)

    def process_row(row):
        # 1. Days Remaining calculation
        delta = (row['Deadline'] - today).days
        row['Days_Remaining'] = delta if row['Status'] != "Closed" else 0
        
        # 2. NEW: Days Since Last Update
        if pd.notnull(row['Last_Updated']):
            row['Days_Since_Update'] = (today - row['Last_Updated']).days
        else:
            row['Days_Since_Update'] = 0

        # 3. Risk Logic
        if row['Status'] == "Closed": row['Risk_Status'] = "✅ Closed"
        elif delta < 0: row['Risk_Status'] = "💀 OVERDUE"
        elif row['Start_Date'] >= row['Deadline']: row['Risk_Status'] = "⚠️ Date Inversion"
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
if "audit_log" not in st.session_state:
    st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Prev", "New", "Audit_Context"])
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# Sidebar Reset Controls
st.sidebar.header("Sentinel Controls")
if st.sidebar.button("📁 Clear Uploaded Files"):
    st.session_state.uploader_key += 1
    st.rerun()
if st.sidebar.button("🗑️ Reset Master Tracker"):
    st.session_state.mra_data = pd.DataFrame()
    st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Prev", "New", "Audit_Context"])
    st.rerun()

# Upload Section
uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True, key=f"up_{st.session_state.uploader_key}")
if uploaded_files:
    if st.button("🚀 Ingest Findings"):
        new_recs = [extract_mras_from_pdf(f.read(), f.name) for f in uploaded_files]
        combined = pd.concat([st.session_state.mra_data, *new_recs], ignore_index=True)
        st.session_state.mra_data = apply_sentinel_logic(combined).drop_duplicates(subset=['MRA_ID'])

# --- MAIN DASHBOARD TABS ---
if not st.session_state.mra_data.empty:
    tab_exec, tab_ledger, tab_roadmap, tab_alerts, tab_audit = st.tabs([
        "📊 Executive Dashboard", "📋 Centralized Ledger", "🗺️ Strategic Roadmap", "📧 Escalation Alerts", "📜 Audit Trail"
    ])

    with tab_exec:
        st.subheader("Portfolio Risk Snapshot")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Master Inventory", len(st.session_state.mra_data))
            risk_c = len(st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀")])
            st.metric("At-Risk Items", risk_c, delta_color="inverse")
        
        # Risk chart
        trend_data = st.session_state.mra_data['Risk_Status'].value_counts().reset_index()
        trend_data.columns = ['Risk_Status', 'Count']
        trend_chart = alt.Chart(trend_data).mark_bar().encode(
            x=alt.X('Count:Q'),
            y=alt.Y('Risk_Status:N', sort='-x', title=None),
            color=alt.Color('Risk_Status:N', scale=alt.Scale(
                domain=["💀 OVERDUE", "🚨 CRITICAL: 75%+", "⚠️ WARNING: 50%+", "🟢 On Track", "✅ Closed"],
                range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"]
            ))
        ).properties(height=250, title="Status Concentration")
        st.altair_chart(trend_chart, use_container_width=True)

    with tab_ledger:
        st.subheader("Interactive Remediation Ledger")
        old_df = st.session_state.mra_data.copy()
        
        # Display editor with NEW "Days Since Update" column visibility
        edited_df = st.data_editor(st.session_state.mra_data, use_container_width=True, num_rows="dynamic", key="led_edit",
                                   column_config={
                                       "Theme": st.column_config.SelectboxColumn(options=list(THEME_REFS.keys()) + ["General / Other"]),
                                       "Reg_Reference": st.column_config.TextColumn("Reg Reference"),
                                       "Days_Since_Update": st.column_config.NumberColumn("Age (Days)", disabled=True, format="%d"),
                                       "Last_Updated": st.column_config.DatetimeColumn(disabled=True)
                                   })
        
        # Audit Check Logic (Also updates Last_Updated timestamp)
        if not edited_df.equals(old_df):
            today = datetime.now().replace(tzinfo=None)
            for idx, row in edited_df.iterrows():
                if idx in old_df.index and row['Status'] != old_df.loc[idx, 'Status']:
                    # Update the Last_Updated timestamp for this row
                    edited_df.at[idx, 'Last_Updated'] = today
                    
                    over_days = (today - pd.to_datetime(row['Deadline']).replace(tzinfo=None)).days
                    ctx = f"⚠️ Post-Deadline ({over_days}d late)" if over_days > 0 else "✅ On-Schedule"
                    new_log = pd.DataFrame([{"Timestamp": today.strftime("%Y-%m-%d %H:%M:%S"), "MRA_ID": row['MRA_ID'], 
                                             "Event": "Status Change", "Prev": old_df.loc[idx, 'Status'], "New": row['Status'], "Audit_Context": ctx}])
                    st.session_state.audit_log = pd.concat([st.session_state.audit_log, new_log], ignore_index=True)
            st.session_state.mra_data = apply_sentinel_logic(edited_df)

    with tab_roadmap:
        st.subheader("Chronological Roadmap")
        chart_df = st.session_state.mra_data.copy().dropna(subset=['Start_Date', 'Deadline'])
        if not chart_df.empty:
            gantt = alt.Chart(chart_df).mark_bar().encode(
                x=alt.X('Start_Date:T'), x2='Deadline:T',
                y=alt.Y('MRA_ID:N', sort='ascending'),
                color=alt.Color('Risk_Status:N', scale=alt.Scale(
                    domain=["💀 OVERDUE", "🚨 CRITICAL: 75%+", "⚠️ WARNING: 50%+", "🟢 On Track", "✅ Closed"],
                    range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"]
                )),
                tooltip=['MRA_ID', 'Theme', 'Owner', 'Status', 'Days_Since_Update']
            ).properties(height=alt.Step(40)).interactive()
            st.altair_chart(gantt, use_container_width=True)

    with tab_alerts:
        critical = st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀")]
        if not critical.empty:
            target = st.selectbox("Select MRA for Escalation:", critical['MRA_ID'])
            row = critical[critical['MRA_ID'] == target].iloc[0]
            st.text_area("Email Draft", f"Subject: URGENT: {row['MRA_ID']} Alert\nRef: {row['Reg_Reference']}\n\nDear {row['Owner']},\n\nFinding {row['MRA_ID']} regarding {row['Theme']} is currently {row['Risk_Status']}.\nDeadline: {row['Deadline'].strftime('%Y-%m-%d')}\nDays Since Last Update: {int(row['Days_Since_Update'])}\n\nPlease update status immediately.", height=180)
        else: st.success("Portfolio healthy.")

    with tab_audit:
        st.dataframe(st.session_state.audit_log, use_container_width=True)
        st.download_button("📥 Export Audit Log", convert_df_to_csv(st.session_state.audit_log), "MRA_Audit.csv", "text/csv")

    st.download_button("📥 Export Master Tracker", convert_df_to_csv(st.session_state.mra_data), "MRA_Sentinel_Export.csv", "text/csv")
