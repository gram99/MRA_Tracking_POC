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

# Thematic mapping dictionary
THEME_KEYWORDS = {
    "Cybersecurity/IT": [r"cyber", r"information security", r"it risk", r"firewall", r"access control"],
    "Financial Crime/AML": [r"aml", r"bsa", r"money laundering", r"kyc", r"sanctions"],
    "Credit Risk": [r"loan", r"credit", r"underwriting", r"allowance", r"cre"],
    "Compliance/Legal": [r"compliance", r"legal", r"regulation", r"consumer protection"],
    "Capital/Liquidity": [r"capital", r"liquidity", r"stress test", r"basel", r"funding"]
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

    # Theme Identification
    identified_theme = "General / Other"
    for theme, patterns in THEME_KEYWORDS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            identified_theme = theme
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
if "audit_log" not in st.session_state:
    st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Previous_Status", "New_Status", "Overdue_Context"])
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# Sidebar
st.sidebar.header("Sentinel Controls")
if st.sidebar.button("📁 Clear Uploaded Files"):
    st.session_state.uploader_key += 1
    st.rerun()

if st.sidebar.button("🗑️ Reset Master Tracker"):
    st.session_state.mra_data = pd.DataFrame()
    st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Previous_Status", "New_Status", "Overdue_Context"])
    st.session_state.uploader_key += 1
    st.rerun()

# Multi-file Uploader
uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True, key=f"pdf_uploader_{st.session_state.uploader_key}")

if uploaded_files:
    if st.button("🚀 Ingest Findings"):
        new_recs = [extract_mras_from_pdf(f.read(), f.name) for f in uploaded_files]
        combined = pd.concat([st.session_state.mra_data, *new_recs], ignore_index=True)
        st.session_state.mra_data = apply_sentinel_logic(combined).drop_duplicates(subset=['MRA_ID'])

if not st.session_state.mra_data.empty:
    # 1. ANALYTICS
    st.subheader("📊 Portfolio Risk Analytics")
    col1, col2 = st.columns(2) 
    
    with col1:
        st.metric("Master Inventory", len(st.session_state.mra_data))
        risk_c = len(st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀")])
        st.metric("Risk Portfolio", risk_c, delta_color="inverse")
    
    with col2:
        # HEATMAP: Theme Concentration
        theme_chart = alt.Chart(st.session_state.mra_data).mark_bar().encode(
            x=alt.X('count():Q', title='Count of Findings'),
            y=alt.Y('Theme:N', title=None, sort='-x'),
            color=alt.Color('Risk_Status:N', scale=alt.Scale(
                domain=["💀 OVERDUE", "🚨 CRITICAL: 75%+", "⚠️ WARNING: 50%+", "🟢 On Track", "✅ Closed"],
                range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"]
            ))
        ).properties(height=200)
        st.altair_chart(theme_chart, use_container_width=True)

    # 2. LEDGER (Thematic Editor)
    st.subheader("📋 Centralized Remediation Ledger")
    
    old_df = st.session_state.mra_data.copy()
    edited_df = st.data_editor(st.session_state.mra_data, 
                               use_container_width=True, 
                               num_rows="dynamic", 
                               key="main_editor",
                               column_config={
                                   "Theme": st.column_config.SelectboxColumn(options=list(THEME_KEYWORDS.keys()) + ["General / Other"])
                               })
    
    # Audit Trace
    if not edited_df.equals(old_df):
        today = datetime.now().replace(tzinfo=None)
        for idx, row in edited_df.iterrows():
            if idx in old_df.index:
                if row['Status'] != old_df.loc[idx, 'Status']:
                    deadline = pd.to_datetime(row['Deadline']).replace(tzinfo=None)
                    over_days = (today - deadline).days
                    ctx = f"⚠️ Post-Deadline ({over_days} days late)" if over_days > 0 else "✅ On-Schedule"
                    
                    new_entry = pd.DataFrame([{
                        "Timestamp": today.strftime("%Y-%m-%d %H:%M:%S"),
                        "MRA_ID": row['MRA_ID'],
                        "Event": "Status Change",
                        "Previous_Status": old_df.loc[idx, 'Status'],
                        "New_Status": row['Status'],
                        "Overdue_Context": ctx
                    }])
                    st.session_state.audit_log = pd.concat([st.session_state.audit_log, new_entry], ignore_index=True)
        st.session_state.mra_data = apply_sentinel_logic(edited_df)

    # 3. ROADMAP
    tab1, tab2, tab3 = st.tabs(["🗺️ Strategic Roadmap", "📧 Alerts", "📜 Audit Trail"])
    
    with tab1:
        gantt = alt.Chart(st.session_state.mra_data).mark_bar().encode(
            x=alt.X('Start_Date:T', title='Timeline'),
            x2='Deadline:T',
            y=alt.Y('MRA_ID:N', sort='ascending', title=None),
            color=alt.Color('Risk_Status:N', scale=alt.Scale(
                domain=["💀 OVERDUE", "🚨 CRITICAL: 75%+", "⚠️ WARNING: 50%+", "🟢 On Track", "✅ Closed"],
                range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"]
            )),
            tooltip=['MRA_ID', 'Theme', 'Owner', 'Status', 'Days_Remaining']
        ).properties(height=alt.Step(40)).interactive()
        st.altair_chart(gantt, use_container_width=True)

    with tab2:
        critical_items = st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀")]
        if not critical_items.empty:
            target = st.selectbox("Select MRA for Alert:", critical_items['MRA_ID'])
            row = critical_items[critical_items['MRA_ID'] == target].iloc
            
            s_lbl = "OVERDUE" if row['Days_Remaining'] < 0 else "CRITICAL"
            email = f"Subject: URGENT: {s_lbl} [{row['Theme']}] Alert - {row['MRA_ID']}\n\nDear {row['Owner']},\n\nFinding {row['MRA_ID']} regarding {row['Theme']} is {s_lbl}.\nDeadline: {row['Deadline'].strftime('%Y-%m-%d')}\n\nPlease update immediately."
            st.text_area("Draft Notification", email, height=180)
        else:
            st.success("No critical alerts required.")

    with tab3:
        if not st.session_state.audit_log.empty:
            st.dataframe(st.session_state.audit_log, use_container_width=True)
            st.download_button("📥 Export Audit Log", convert_df_to_csv(st.session_state.audit_log), "MRA_Audit_Trail.csv", "text/csv")
        else:
            st.info("No status changes recorded.")

    st.download_button("📥 Export Master Tracker", convert_df_to_csv(st.session_state.mra_data), "MRA_Master_Tracker.csv", "text/csv")
