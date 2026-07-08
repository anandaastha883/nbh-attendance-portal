import streamlit as st
import pandas as pd
import sqlite3
import io
import hashlib
from datetime import datetime

# --- 1. SETTINGS & HELPERS ---
st.set_page_config(page_title="NBH Attendance Pro", layout="wide")

def make_hash(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db(): return sqlite3.connect('societies.db', check_same_thread=False)

# This function finds categories in the CSV and adds them to DB if new
def sync_and_get_categories(email, df):
    if 'Type' not in df.columns: return []
    found_types = df['Type'].unique().tolist()
    conn = get_db(); cursor = conn.cursor()
    for t in found_types:
        res = cursor.execute('SELECT 1 FROM category_rules WHERE society_email=? AND category_name=?', (email, t)).fetchone()
        if not res:
            cursor.execute('INSERT INTO category_rules VALUES (?, ?, 8.0, 4.0)', (email, t))
    conn.commit(); conn.close()
    return found_types

def update_db(email, week_off, hols, active_rules):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute('UPDATE users SET weekly_off=?, holidays=? WHERE email=?', (week_off, hols, email))
    for cat, v in active_rules.items():
        cursor.execute('UPDATE category_rules SET present_threshold=?, half_day_threshold=? WHERE society_email=? AND category_name=?', (v['p'], v['h'], email, cat))
    conn.commit(); conn.close()

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00"]: return 0.0
    try:
        if isinstance(t, (int, float)): return float(t)
        p = str(t).split(':')
        return int(p[0]) + (int(p[1])/60.0)
    except: return 0.0

# --- 2. AUTHENTICATION ---
if 'auth' not in st.session_state:
    st.session_state.auth = {'logged_in': False, 'user': None, 'name': None}
if 'current_cats' not in st.session_state:
    st.session_state.current_cats = []

if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood Society Portal")
    with st.form("login"):
        e = st.text_input("Email")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            conn = get_db()
            user = pd.read_sql(f"SELECT * FROM users WHERE email='{e}'", conn)
            conn.close()
            if not user.empty and make_hash(p) == user.iloc[0]['password']:
                st.session_state.auth = {'logged_in': True, 'user': e, 'name': user.iloc[0]['society_name']}
                st.rerun()
            else: st.error("❌ Invalid Credentials")
else:
    user_email = st.session_state.auth['user']
    full_name = st.session_state.auth['name']

    # --- TOP LEVEL UPLOADER ---
    # This must happen before sidebar rules are drawn
    st.title(f"🏢 {full_name} Portal")
    f = st.file_uploader("Upload Attendance CSV", type="csv")
    
    if f:
        df_raw = pd.read_csv(f)
        df_raw.columns = [c.strip().title() for c in df_raw.columns]
        
        # Identify categories in the file
        new_cats = sync_and_get_categories(user_email, df_raw)
        
        # If the categories in the file are different than what we're showing, refresh
        if set(st.session_state.current_cats) != set(new_cats):
            st.session_state.current_cats = new_cats
            st.rerun()

    # --- LOAD CONFIG FROM DB ---
    conn = get_db()
    u_info = pd.read_sql(f"SELECT * FROM users WHERE email='{user_email}'", conn).iloc[0]
    
    # Only load rules for categories present in the current file
    if st.session_state.current_cats:
        cat_placeholders = ",".join(["?"] * len(st.session_state.current_cats))
        query = f"SELECT * FROM category_rules WHERE society_email=? AND category_name IN ({cat_placeholders})"
        rules_df = pd.read_sql(query, conn, params=[user_email] + st.session_state.current_cats)
    else:
        rules_df = pd.DataFrame()
    conn.close()

    # --- SIDEBAR UI ---
    st.sidebar.title(f"👋 Welcome")
    if st.sidebar.button("Logout"):
        st.session_state.auth = {'logged_in': False}
        st.session_state.current_cats = []
        st.rerun()

    active_rules = {}
    st.sidebar.header("⚙️ Rules Configuration")
    
    if not rules_df.empty:
        for _, r in rules_df.iterrows():
            cat = r['category_name']
            with st.sidebar.expander(f"🛠️ {cat} Rules"):
                p_v = st.sidebar.slider("Present (Hrs)", 0.0, 12.0, float(r['present_threshold']), key=f"p_{cat}")
                h_v = st.sidebar.slider("Half Day (Hrs)", 0.0, 8.0, float(r['half_day_threshold']), key=f"h_{cat}")
                active_rules[cat] = {'p': p_v, 'h': h_v}
    else:
        st.sidebar.info("💡 Upload a CSV to view and manage category rules.")

    st.sidebar.header("📅 Society Settings")
    days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    sel_off = st.sidebar.selectbox("Weekly Off", days, index=days.index(u_info['weekly_off']) if u_info['weekly_off'] in days else 0)
    h_input = st.sidebar.text_area("Holidays (YYYY-MM-DD)", value=u_info['holidays'])

    if st.sidebar.button("💾 Save Settings"):
        update_db(user_email, sel_off, h_input, active_rules)
        st.toast("Database Updated!")

    # --- ENGINE & DASHBOARD ---
    if f:
        if st.button("🚀 Process Attendance Data"):
            hols = [h.strip() for h in h_input.split(",")] if h_input else []
            date_cols = [col.split(' ')[0] for col in df_raw.columns if 'Duration' in col]
            tidy = []
            for _, row in df_raw.iterrows():
                for d in date_cols:
                    raw_dur = str(row.get(f"{d} Duration", "0"))
                    hrs = round(time_to_decimal(raw_dur), 2)
                    emp_t = row.get('Type', 'Security')
                    r = active_rules.get(emp_t, {'p': 8, 'h': 4})
                    
                    try: is_off = pd.to_datetime(d).strftime('%A') == sel_off
                    except: is_off = False
                    
                    if hrs >= r['p']: s = "Present"
                    elif hrs >= r['h']: s = "Half Day"
                    elif d in hols: s = "Holiday"
                    elif is_off: s = "Weekly Off"
                    else: s = "Absent"
                    tidy.append({"Name": row['Name'], "Date": d, "Hours": hrs, "Status": s, "Type": emp_t})
            st.session_state.main_data = pd.DataFrame(tidy)

    if 'main_data' in st.session_state:
        res = st.session_state.main_data
        summary = res.groupby(['Name', 'Type', 'Status']).size().unstack(fill_value=0).reset_index().set_index('Name')
        
        st.subheader("📊 Summary")
        event = st.dataframe(summary, use_container_width=True, on_select="rerun", selection_mode="single-row", key="table")
        
        if sel := event.get("selection", {}).get("rows", []):
            name = summary.index[sel[0]]
            p_df = res[res['Name'] == name].sort_values('Date')
            st.divider()
            st.header(f"👤 Spotlight: {name}")
            
            # Colored Strip
            strip = "<div style='display:flex; gap:3px; overflow-x:auto;'>"
            for _, r_data in p_df.iterrows():
                c = "green" if r_data['Status']=="Present" else "orange" if r_data['Status']=="Half Day" else "red" if r_data['Status']=="Absent" else "blue"
                strip += f"<div style='background:{c}; color:white; padding:5px; border-radius:3px; font-size:10px; text-align:center; min-width:40px;'>{r_data['Date'][-2:]}<br>{r_data['Status'][0]}</div>"
            st.markdown(strip + "</div>", unsafe_allow_html=True)
            st.line_chart(p_df.set_index('Date')['Hours'])
        
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            summary.to_excel(writer, sheet_name='Summary'); res.to_excel(writer, sheet_name='Logs')
        st.download_button("📥 Download Excel Report", buf.getvalue(), "NBH_Report.xlsx")
