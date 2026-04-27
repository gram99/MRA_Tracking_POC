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

    theme, ref = "General / Other", "N/A"
    for t, config in THEME_REFS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in config["keywords"]):
            theme, ref = t, config["ref"]
            break

    extracted = []
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    for i, date_str in enumerate(date_matches if date_matches else ["Manual Entry"]):
        try: deadline = pd.to_datetime(date_str).to_pydatetime().replace(tzinfo=None)
        except: deadline = today + timedelta(days=90)
        extracted.append({
            "MRA_ID": f"{agency}-{filename[:5].upper()}-{i+1:02}", 
            "Theme": theme, "Reg_Reference": ref, "Owner": "LOB Pending", 
            "Start_Date": today - timedelta(days=30), "Deadline": deadline, 
            "Status": "In Progress", "Last_Updated": today, "Days_Since_Update": 0
        })
    return pd.DataFrame(extracted)

# --- LOGIC ---
def apply_sentinel_logic(df):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    for c in ["Deadline", "Start_Date", "Last_Updated"]:
        df[c] = pd.to_datetime(df[c], errors='coerce').dt.tz_localize(None)
    
    def process(row):
        row['Days_Since_Update'] = max(0, (today - row['Last_Updated'].replace(tzinfo=None)).days)
        stale = "🧊 STALE: " if row['Days_Since_Update'] > 30 and row['Status'] != "Closed" else ""
        delta = (row['Deadline'] - today).days
        row['Days_Remaining'] = delta if row['Status'] != "Closed" else 0
        
        if row['Status'] == "Closed": row['Risk_Status'] = "✅ Closed"
        elif delta < 0: row['Risk_Status'] = f"{stale}💀 OVERDUE"
        elif row['Start_Date'] >= row['Deadline']: row['Risk_Status'] = "⚠️ Date Inversion"
        else:
            w = (row['Deadline'] - row['Start_Date']).days
            e = (today - row['Start_Date']).days
            burn = e / w if w > 0 else 1
            if burn >= 0.75: row['Risk_Status'] = f"{stale}🚨 CRITICAL"
            elif burn >= 0.50: row['Risk_Status'] = f"{stale}⚠️ WARNING"
            else: row['Risk_Status'] = f"{stale}🟢 On Track"
        return row
    return df.apply(process, axis=1)

# --- UI ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")
st.title("🛡️ MRA Sentinel: Command Center")

if "mra_data" not in st.session_state: st.session_state.mra_data = pd.DataFrame()
if "audit_log" not in st.session_state: st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Prev", "New", "Audit_Context"])
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0

# Sidebar
if st.sidebar.button("📁 Clear Files"): st.session_state.uploader_key += 1; st.rerun()
if st.sidebar.button("🗑️ Reset Tracker"): 
    st.session_state.mra_data = pd.DataFrame(); 
    st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Prev", "New", "Audit_Context"]); 
    st.rerun()

up = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True, key=f"up_{st.session_state.uploader_key}")
if up and st.button("🚀 Ingest"):
    new = pd.concat([extract_mras_from_pdf(f.read(), f.name) for f in up])
    st.session_state.mra_data = apply_sentinel_logic(pd.concat([st.session_state.mra_data, new], ignore_index=True)).drop_duplicates(subset=['MRA_ID'])

if not st.session_state.mra_data.empty:
    tabs = st.tabs(["📊 Executive Dashboard", "📋 Centralized Ledger", "🗺️ Strategic Roadmap", "📧 Alerts", "📜 Audit Trail"])

    with tabs[0]:
        st.subheader("Executive Risk Oversight")
        c1, c2 = st.columns([1, 2])
        chart_df = st.session_state.mra_data.copy()
        chart_df['Simple_Risk'] = chart_df['Risk_Status'].str.replace("🧊 STALE: ", "")
        
        with c1:
            st.metric("Total MRAs", len(st.session_state.mra_data))
            # --- NEW: DAYS OVERDUE BENCHMARK ---
            overdue_items = chart_df[chart_df['Days_Remaining'] < 0]
            max_overdue = abs(overdue_items['Days_Remaining'].min()) if not overdue_items.empty else 0
            st.metric("Max Days Overdue", f"{int(max_overdue)} d", delta_color="inverse")
            
            # --- FIXED DONUT: Portfolio Health (Current State) ---
            st.write("**Portfolio Health Distribution**")
            donut_data = chart_df['Simple_Risk'].value_counts().reset_index(name='count')
            donut = alt.Chart(donut_data).mark_arc(innerRadius=50).encode(
                theta="count:Q",
                color=alt.Color("Simple_Risk:N", scale=alt.Scale(
                    domain=["💀 OVERDUE", "🚨 CRITICAL", "⚠️ WARNING", "🟢 On Track", "✅ Closed"],
                    range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"]
                ), legend=None),
                tooltip=["Simple_Risk", "count"]
            ).properties(height=200)
            st.altair_chart(donut, use_container_width=True)

        with c2:
            heatmap = alt.Chart(chart_df).mark_rect().encode(
                x=alt.X('Simple_Risk:N', title="Risk Tier", sort=["💀 OVERDUE", "🚨 CRITICAL", "⚠️ WARNING", "🟢 On Track", "✅ Closed"]),
                y=alt.Y('Owner:N', title=None),
                color=alt.Color('count():Q', scale=alt.Scale(scheme='reds'), title="Freq"),
                tooltip=['Owner', 'Simple_Risk', 'count()']
            ).properties(title="Risk Concentration", height=320, width=450)
            st.altair_chart(heatmap, use_container_width=False)

    with tabs[1]:
        old = st.session_state.mra_data.copy()
        ed = st.data_editor(st.session_state.mra_data, use_container_width=True, num_rows="dynamic", key="led_edit")
        if not ed.equals(old):
            now = datetime.now().replace(tzinfo=None)
            for i, r in ed.iterrows():
                if i in old.index and r['Status'] != old.loc[i, 'Status']:
                    ed.at[i, 'Last_Updated'] = now
                    over = (now - pd.to_datetime(r['Deadline']).replace(tzinfo=None)).days
                    ctx = f"⚠️ Post-Deadline ({over}d late)" if over > 0 else "✅ On-Schedule"
                    new_log = pd.DataFrame([{"Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "MRA_ID": r['MRA_ID'], "Event": "Status Change", "Prev": old.loc[i, 'Status'], "New": r['Status'], "Audit_Context": ctx}])
                    st.session_state.audit_log = pd.concat([st.session_state.audit_log, new_log], ignore_index=True)
            st.session_state.mra_data = apply_sentinel_logic(ed)

    with tabs[2]:
        rdf = st.session_state.mra_data.copy()
        rdf['Chart_Risk'] = rdf['Risk_Status'].str.replace("🧊 STALE: ", "")
        gantt = alt.Chart(rdf.dropna(subset=['Start_Date', 'Deadline'])).mark_bar().encode(
            x='Start_Date:T', x2='Deadline:T', y=alt.Y('MRA_ID:N', title=None),
            color=alt.Color('Chart_Risk:N', scale=alt.Scale(domain=["💀 OVERDUE", "🚨 CRITICAL", "⚠️ WARNING", "🟢 On Track", "✅ Closed"], range=["#000000", "#FF4B4B", "#FFAA00", "#00CC96", "#2E7D32"])),
            tooltip=['MRA_ID', 'Owner', 'Status', 'Days_Since_Update', 'Days_Remaining']
        ).properties(height=alt.Step(40)).interactive()
        st.altair_chart(gantt, use_container_width=True)

    with tabs[3]:
        crit = st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀|🧊")]
        if not crit.empty:
            target = st.selectbox("Select MRA for Alert:", crit['MRA_ID'])
            r = crit[crit['MRA_ID'] == target].iloc[0]
            st.text_area("Email Draft", f"Subject: URGENT: {r['MRA_ID']} Alert\n\nDear {r['Owner']},\n\nFinding {r['MRA_ID']} is flagged as {r['Risk_Status']}.\nDeadline: {r['Deadline'].strftime('%Y-%m-%d')}\nDays Since Last Update: {int(r['Days_Since_Update'])}\nDays Overdue: {abs(int(r['Days_Remaining'])) if r['Days_Remaining'] < 0 else 0}\n\nPlease update status immediately.", height=150)

    with tabs[4]:
        st.dataframe(st.session_state.audit_log, use_container_width=True)
        st.download_button("📥 Export Audit Log", convert_df_to_csv(st.session_state.audit_log), "MRA_Audit.csv", "text/csv")

    st.download_button("📥 Export Master Tracker", convert_df_to_csv(st.session_state.mra_data), "MRA_Master_Tracker.csv", "text/csv")
