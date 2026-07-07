import streamlit as st
import pandas as pd
import sqlite3
import io
import hashlib
from datetime import datetime

st.set_page_config(page_title="NBH Attendance Pro", layout="wide")

def make_hash(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_db():
    return sqlite3.connect('societies.db', check_same_thread=False)

def sync_categories(email, df):
    if 'Type' not in df.columns: return False
    found_types = df['Type'].unique()
    conn = get_db()
    cursor = conn.cursor()
    new_found = False
    for t in found_types:
        res = cursor.execute('SELECT 1 FROM category_rules WHERE society_email = ? AND category_name = ?', (email, t)).fetchone()
        if not res:
            cursor.execute('INSERT INTO category_rules VALUES (?, ?, 8.0, 4.0)', (email, t))
            new_found = True
    conn.commit()
    conn.close()
    return new_found

def update_db_settings(email, week_off, hols_str, active_rules):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET weekly_off = ?, holidays = ? WHERE email = ?', (week_off, hols_str, email))
    for cat, v in active_rules.items():
        cursor.execute('UPDATE category_rules SET present_threshold = ?, half_day_threshold = ? WHERE society_email = ? AND category_name = ?', (v['p'], v['h'], email, cat))
    conn.commit()
    conn.close()

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00"]: return 0.0
    try:
        if isinstance(t, (int, float)): return float(t)
        p = str(t).split(':')
        return int(p[0]) + (int(p[1])/60.0)
    except: return 0.0

# --- SESSION STATE ---
if 'auth' not in st.session_state:
    st.session_state.auth = {'logged_in': False, 'user': None, 'name': None}
if 'settings_loaded' not in st.session_state:
    st.session_state.settings_loaded = False

# --- UI FLOW ---
if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood Society Portal")
    with st.form("login_form"):
        e = st.text_input("Email")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            conn = get_db()
            user_row = pd.read_sql(f"SELECT * FROM users WHERE email='{e}'", conn)
            conn.close()
            if not user_row.empty and make_hash(p) == user_row.iloc[0]['password']:
                st.session_state.auth = {'logged_in': True, 'user': e, 'name': user_row.iloc[0]['society_name']}
                st.rerun()
            else: st.error("❌ Invalid Login")
else:
    user_email = st.session_state.auth['user']
    full_name = st.session_state.auth['name']

    # --- UPLOADER (TOP LEVEL) ---
    st.title(f"🏢 {full_name} Portal")
    f = st.file_uploader("Upload Attendance CSV", type="csv")
    if f:
        df_raw = pd.read_csv(f)
        if sync_categories(user_email, df_raw):
            st.session_state.settings_loaded = False
            st.rerun()

    # --- LOAD SETTINGS ---
    if not st.session_state.settings_loaded:
        conn = get_db()
        u_df = pd.read_sql(f"SELECT * FROM users WHERE email='{user_email}'", conn)
        r_df = pd.read_sql(f"SELECT * FROM category_rules WHERE society_email='{user_email}'", conn)
        conn.close()
        st.session_state.db_weekly_off = u_df.iloc[0]['weekly_off']
        st.session_state.db_holidays = u_df.iloc[0]['holidays']
        st.session_state.rules_list = r_df.to_dict('records')
        st.session_state.settings_loaded = True

    # --- SIDEBAR UI ---
    st.sidebar.title(f"👋 Welcome")
    if st.sidebar.button("Logout"):
        st.session_state.auth = {'logged_in': False}
        st.session_state.settings_loaded = False
        st.rerun()

    st.sidebar.header("⚙️ Rules")
    active_rules = {}
    for rule in st.session_state.rules_list:
        cat = rule['category_name']
        with st.sidebar.expander(f"🛠️ {cat}"):
            p_v = st.sidebar.slider("Present", 0.0, 12.0, float(rule['present_threshold']), key=f"p_{cat}")
            h_v = st.sidebar.slider("Half Day", 0.0, 8.0, float(rule['half_day_threshold']), key=f"h_{cat}")
            active_rules[cat] = {'p': p_v, 'h': h_v}

    days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    sel_off = st.sidebar.selectbox("Weekly Off", days, index=days.index(st.session_state.db_weekly_off) if st.session_state.db_weekly_off in days else 0)
    h_input = st.sidebar.text_area("Holidays", value=st.session_state.db_holidays)

    if st.sidebar.button("💾 Save All Settings"):
        update_db_settings(user_email, sel_off, h_input, active_rules)
        st.session_state.settings_loaded = False 
        st.rerun()

    # --- RESULTS ---
    if f is not None:
        if st.button("🚀 Run Analysis"):
            hols = [h.strip() for h in h_input.split(",")] if h_input else []
            date_cols = [col.split(' ')[0] for col in df_raw.columns if 'Duration' in col]
            tidy = []
            for _, row in df_raw.iterrows():
                for d in date_cols:
                    raw_dur = row.get(f"{d} Duration", 0)
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
            
            processed = pd.DataFrame(tidy)
            st.session_state.main_data = processed

    if 'main_data' in st.session_state:
        res = st.session_state.main_data
        summary = res.groupby(['Name', 'Type', 'Status']).size().unstack(fill_value=0).reset_index().set_index('Name')
        st.subheader("📊 Summary")
        event = st.dataframe(summary, use_container_width=True, on_select="rerun", selection_mode="single-row", key="tab")
        
        sel = event.get("selection", {}).get("rows", [])
        if sel:
            name = summary.index[sel[0]]
            p_df = res[res['Name'] == name].sort_values('Date')
            st.divider()
            st.header(f"👤 {name}")
            strip = "<div style='display:flex; gap:3px;'>"
            for _, row_data in p_df.tail(14).iterrows():
                c = "green" if row_data['Status']=="Present" else "orange" if row_data['Status']=="Half Day" else "red"
                strip += f"<div style='background:{c}; color:white; padding:4px; border-radius:3px; font-size:10px; text-align:center; min-width:35px;'>{row_data['Date'][-2:]}<br>{row_data['Status'][0]}</div>"
            st.markdown(strip + "</div>", unsafe_allow_html=True)
            st.line_chart(p_df.set_index('Date')['Hours'])
