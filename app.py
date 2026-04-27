import streamlit as st
import pandas as pd
import altair as alt
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io

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

RISK_COLORS = {
    "💀 OVERDUE": "#000000",
    "🚨 CRITICAL": "#FF4B4B",
    "⚠️ WARNING": "#FFAA00",
    "🟢 On Track": "#00CC96",
    "✅ Closed": "#2E7D32"
}

# --- PDF GENERATOR ---
def generate_exec_pdf(df, risk_counts):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica-Bold", 18)
    p.drawString(100, height - 80, "MRA Sentinel: Executive Summary")
    p.setFont("Helvetica", 12)
    p.drawString(100, height - 100, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # Metrics
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, height - 140, "Key Metrics")
    p.setFont("Helvetica", 12)
    p.drawString(120, height - 160, f"Total MRAs in Portfolio: {len(df)}")
    
    overdue_val = abs(df[df['Days_Remaining'] < 0]['Days_Remaining'].min()) if not df[df['Days_Remaining'] < 0].empty else 0
    p.drawString(120, height - 180, f"Max Days Overdue: {int(overdue_val)}")

    # Portfolio Health
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, height - 220, "Portfolio Health Distribution")
    y_pos = height - 240
    p.setFont("Helvetica", 12)
    for status, count in risk_counts.items():
        p.drawString(120, y_pos, f"- {status}: {count}")
        y_pos -= 20

    p.showPage()
    p.save()
    return buffer.getvalue()

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
            theme, ref = t, config["ref"]; break
    extracted = []
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    for i, date_str in enumerate(date_matches if date_matches else ["Manual Entry"]):
        try: dl = pd.to_datetime(date_str).to_pydatetime().replace(tzinfo=None)
        except: dl = today + timedelta(days=90)
        extracted.append({"MRA_ID": f"{agency}-{filename[:5].upper()}-{i+1:02}", "Theme": theme, "Reg_Reference": ref, "Owner": "LOB Pending", "Start_Date": today - timedelta(days=30), "Deadline": dl, "Status": "In Progress", "Last_Updated": today, "Days_Since_Update": 0})
    return pd.DataFrame(extracted)

# --- LOGIC ---
def apply_sentinel_logic(df):
    if df.empty: return df
    today = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    for c in ["Deadline", "Start_Date", "Last_Updated"]:
        df[c] = pd.to_datetime(df[c], errors='coerce').dt.tz_localize(None)
    def process(row):
        row['Days_Since_Update'] = max(0, (today - row['Last_Updated'].replace(tzinfo=None)).days)
        delta = (row['Deadline'] - today).days
        row['Days_Remaining'] = delta if row['Status'] != "Closed" else 0
        if row['Status'] == "Closed": row['Risk_Status'] = "✅ Closed"
        elif delta < 0: row['Risk_Status'] = "💀 OVERDUE"
        elif row['Start_Date'] >= row['Deadline']: row['Risk_Status'] = "⚠️ Date Inversion"
        else:
            w = (row['Deadline'] - row['Start_Date']).days
            e = (today - row['Start_Date']).days
            burn = e / w if w > 0 else 1
            if burn >= 0.75: row['Risk_Status'] = "🚨 CRITICAL"
            elif burn >= 0.50: row['Risk_Status'] = "⚠️ WARNING"
            else: row['Risk_Status'] = "🟢 On Track"
        return row
    return df.apply(process, axis=1)

# --- UI ---
st.set_page_config(page_title="MRA Sentinel", layout="wide")
st.title("🛡️ MRA Sentinel: Command Center")

if "mra_data" not in st.session_state: st.session_state.mra_data = pd.DataFrame()
if "audit_log" not in st.session_state: st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Prev", "New", "Audit_Context"])
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0

if st.sidebar.button("📁 Clear Files"): st.session_state.uploader_key += 1; st.rerun()
if st.sidebar.button("🗑️ Reset Tracker"): 
    st.session_state.mra_data = pd.DataFrame(); st.session_state.audit_log = pd.DataFrame(columns=["Timestamp", "MRA_ID", "Event", "Prev", "New", "Audit_Context"]); st.rerun()

up = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True, key=f"up_{st.session_state.uploader_key}")
if up and st.button("🚀 Ingest"):
    new = pd.concat([extract_mras_from_pdf(f.read(), f.name) for f in up])
    st.session_state.mra_data = apply_sentinel_logic(pd.concat([st.session_state.mra_data, new], ignore_index=True)).drop_duplicates(subset=['MRA_ID'])

if not st.session_state.mra_data.empty:
    tabs = st.tabs(["📊 Executive Dashboard", "📋 Centralized Ledger", "🗺️ Strategic Roadmap", "📧 Alerts", "📜 Audit Trail"])

    with tabs[0]:
        st.subheader("Executive Risk Oversight")
        c1, c2 = st.columns(2)
        chart_df = st.session_state.mra_data.copy()
        chart_df['Simple_Risk'] = chart_df['Risk_Status'].str.replace("🧊 STALE: ", "")
        risk_counts = chart_df['Simple_Risk'].value_counts().to_dict()
        
        with c1:
            st.metric("Total MRAs", len(st.session_state.mra_data))
            overdue_items = chart_df[chart_df['Days_Remaining'] < 0]
            max_overdue = abs(overdue_items['Days_Remaining'].min()) if not overdue_items.empty else 0
            st.metric("Max Days Overdue", int(max_overdue), delta_color="inverse")
            
            # DONUT: Reduced font and 2-column legend
            st.write("**Portfolio Health Distribution**")
            donut = alt.Chart(chart_df).mark_arc(innerRadius=50).encode(
                theta="count():Q",
                color=alt.Color("Simple_Risk:N", scale=alt.Scale(domain=list(RISK_COLORS.keys()), range=list(RISK_COLORS.values())), 
                                legend=alt.Legend(title=None, orient="bottom", labelFontSize=10, columns=2, symbolSize=100)),
                tooltip=["Simple_Risk", "count()"]
            ).properties(height=250)
            st.altair_chart(donut, use_container_width=True)

            # PDF Export Button
            pdf_data = generate_exec_pdf(chart_df, risk_counts)
            st.download_button("📄 Export Executive Summary (PDF)", pdf_data, "MRA_Executive_Summary.pdf", "application/pdf")

        with c2:
            heatmap = alt.Chart(chart_df).mark_rect().encode(
                x=alt.X('Simple_Risk:N', title="Risk Tier", sort=list(RISK_COLORS.keys())),
                y=alt.Y('Owner:N', title=None),
                color=alt.Color('Simple_Risk:N', scale=alt.Scale(domain=list(RISK_COLORS.keys()), range=list(RISK_COLORS.values())), legend=None),
                tooltip=['Owner', 'Simple_Risk', 'count()']
            ).properties(title="Risk Concentration Heatmap", height=350, width=500)
            text = heatmap.mark_text(baseline='middle').encode(text='count():Q', color=alt.value('white'))
            st.altair_chart(heatmap + text, use_container_width=False)

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
            color=alt.Color('Chart_Risk:N', scale=alt.Scale(domain=list(RISK_COLORS.keys()), range=list(RISK_COLORS.values()))),
            tooltip=['MRA_ID', 'Owner', 'Status', 'Days_Remaining']
        ).properties(height=alt.Step(40)).interactive()
        st.altair_chart(gantt, use_container_width=True)

    with tabs[3]:
        crit = st.session_state.mra_data[st.session_state.mra_data['Risk_Status'].str.contains("🚨|💀")]
        if not crit.empty:
            target = st.selectbox("Select MRA for Alert:", crit['MRA_ID'])
            r = crit[crit['MRA_ID'] == target].iloc[0]
            st.text_area("Email Draft", f"Subject: URGENT: {r['MRA_ID']} Alert\n\nDear {r['Owner']},\n\nFinding {r['MRA_ID']} is flagged as {r['Risk_Status']}.\nDeadline: {r['Deadline'].strftime('%Y-%m-%d')}\nDays Overdue: {abs(int(r['Days_Remaining'])) if r['Days_Remaining'] < 0 else 0}\n\nPlease update status immediately.", height=150)

    with tabs[4]:
        st.dataframe(st.session_state.audit_log, use_container_width=True)
        st.download_button("📥 Export Audit Log", convert_df_to_csv(st.session_state.audit_log), "MRA_Audit.csv", "text/csv")

    st.download_button("📥 Export Master Tracker", convert_df_to_csv(st.session_state.mra_data), "MRA_Master_Tracker.csv", "text/csv")
