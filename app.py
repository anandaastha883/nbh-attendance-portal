import streamlit as st
import pandas as pd
import sqlite3
import io
import hashlib
from datetime import datetime

# --- 1. PAGE CONFIG ---
st.set_page_config(page_title="NBH Attendance Pro", layout="wide")

def make_hash(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- 2. DATABASE HELPERS ---
def get_db():
    return sqlite3.connect('societies.db', check_same_thread=False)

def update_db_settings(email, week_off, hols_str, active_rules):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET weekly_off = ?, holidays = ? WHERE email = ?', (week_off, hols_str, email))
    for cat, v in active_rules.items():
        cursor.execute('UPDATE category_rules SET present_threshold = ?, half_day_threshold = ? WHERE society_email = ? AND category_name = ?', (v['p'], v['h'], email, cat))
    conn.commit()
    conn.close()

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00", "N/A"]: return 0.0
    try:
        if isinstance(t, (int, float)): return float(t)
        parts = str(t).split(':')
        return int(parts[0]) + (int(parts[1])/60.0)
    except: return 0.0

# --- 3. SESSION STATE ---
if 'auth' not in st.session_state:
    st.session_state.auth = {'logged_in': False, 'user': None, 'name': None}
if 'settings_loaded' not in st.session_state:
    st.session_state.settings_loaded = False

# --- 4. LOGIN ---
def login_user(email, password):
    conn = get_db()
    user_row = pd.read_sql(f"SELECT * FROM users WHERE email='{email}'", conn)
    conn.close()
    if not user_row.empty:
        if make_hash(password) == user_row.iloc[0]['password']:
            st.session_state.auth = {'logged_in': True, 'user': email, 'name': user_row.iloc[0]['society_name']}
            return True
    return False

# --- 5. UI FLOW ---
if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood Society Portal")
    with st.form("login"):
        e = st.text_input("Email")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            if login_user(e, p): st.rerun()
            else: st.error("❌ Invalid Login")
else:
    user_email = st.session_state.auth['user']
    full_name = st.session_state.auth['name']

    if st.sidebar.button("Logout"):
        st.session_state.auth = {'logged_in': False, 'user': None, 'name': None}
        st.session_state.settings_loaded = False
        st.rerun()

    # LOAD SETTINGS
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
    st.sidebar.title(f"👋 {full_name}")
    st.sidebar.header("⚙️ Settings")
    
    current_active_rules = {}
    for rule in st.session_state.rules_list:
        cat = rule['category_name']
        with st.sidebar.expander(f"🛠️ {cat} Rules"):
            p_val = st.sidebar.slider("Present", 0.0, 12.0, float(rule['present_threshold']), key=f"p_{cat}")
            h_val = st.sidebar.slider("Half Day", 0.0, 8.0, float(rule['half_day_threshold']), key=f"h_{cat}")
            current_active_rules[cat] = {'p': p_val, 'h': h_val}

    days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    def_idx = days.index(st.session_state.db_weekly_off) if st.session_state.db_weekly_off in days else 0
    sel_off = st.sidebar.selectbox("Weekly Off", days, index=def_idx)
    
    # IMPROVED HOLIDAY INPUT
    st.sidebar.markdown("**Holidays Setup**")
    h_input = st.sidebar.text_area(
        "Enter dates (YYYY-MM-DD)", 
        value=st.session_state.db_holidays,
        placeholder="2024-01-01, 2024-08-15, 2024-10-02",
        help="Separate dates with commas"
    )
    # CLEANING THE LIST: Removes spaces and empty entries
    hols_list = [h.strip() for h in h_input.split(",") if h.strip()]

    if st.sidebar.button("💾 Save All Settings"):
        update_db_settings(user_email, sel_off, ",".join(hols_list), current_active_rules)
        st.session_state.settings_loaded = False 
        st.toast("Settings Saved!", icon="💾")

    # --- ENGINE ---
    def process_data(df, r_dict, off_name, hols):
        date_cols = [col.split(' ')[0] for col in df.columns if 'Duration' in col]
        tidy = []
        for _, row in df.iterrows():
            for d in date_cols:
                hrs = round(time_to_decimal(row.get(f"{d} Duration", 0)), 2)
                emp_type = row.get('Type', 'Security')
                r = r_dict.get(emp_type, {'p': 8, 'h': 4})
                
                # Logic with Safety Checks
                try:
                    is_off = pd.to_datetime(d).strftime('%A') == off_name
                except:
                    is_off = False
                    
                if hrs >= r['p']: s = "Present"
                elif hrs >= r['h']: s = "Half Day"
                elif d in hols: s = "Holiday"
                elif is_off: s = "Weekly Off"
                else: s = "Absent"
                
                tidy.append({"Name": row['Name'], "Date": d, "Hours": hrs, "Status": s, 
                             "In": row.get(f"{d} Check In", "N/A"), "Out": row.get(f"{d} Check Out", "N/A"), "Type": emp_type})
        return pd.DataFrame(tidy)

    # --- DASHBOARD ---
    st.title(f"🏢 {full_name} Portal")
    f = st.file_uploader("Upload Attendance CSV", type="csv")
    if f:
        df_raw = pd.read_csv(f)
        if st.button("🚀 Process Data"):
            st.session_state.main_data = process_data(df_raw, current_active_rules, sel_off, hols_list)

    if 'main_data' in st.session_state:
        m_df = st.session_state.main_data
        summary = m_df.groupby(['Name', 'Type', 'Status']).size().unstack(fill_value=0).reset_index().set_index('Name')
        
        st.subheader("📊 Summary")
        event = st.dataframe(summary, use_container_width=True, on_select="rerun", selection_mode="single-row", key="table_click")
        
        sel = event.get("selection", {}).get("rows", [])
        if sel:
            name = summary.index[sel[0]]
            p_df = m_df[m_df['Name'] == name].sort_values('Date')
            st.divider()
            st.header(f"👤 {name}")
            
            # Heatmap Strip
            strip = "<div style='display:flex; gap:3px;'>"
            for _, r in p_df.tail(14).iterrows():
                c = "green" if r['Status']=="Present" else "orange" if r['Status']=="Half Day" else "red" if r['Status']=="Absent" else "blue"
                strip += f"<div style='background:{c}; color:white; padding:4px; border-radius:3px; font-size:10px; text-align:center; min-width:35px;'>{r['Date'][-2:]}<br>{r['Status'][0]}</div>"
            st.markdown(strip + "</div>", unsafe_allow_html=True)
            
            log_event = st.dataframe(p_df[['Date', 'Hours', 'Status']], use_container_width=True, on_select="rerun", selection_mode="single-row", key="day_click")
            day_sel = log_event.get("selection", {}).get("rows", [])
            if day_sel:
                day = p_df.iloc[day_sel[0]]
                st.info(f"📍 {day['Date']} | {day['In']} → {day['Out']} ({day['Hours']} hrs)")
            st.line_chart(person_df := p_df.set_index('Date')['Hours'])
        
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            summary.to_excel(writer, sheet_name='Summary'); m_df.to_excel(writer, sheet_name='Logs')
        st.download_button("📥 Download Report", buf.getvalue(), "NBH_Report.xlsx")
