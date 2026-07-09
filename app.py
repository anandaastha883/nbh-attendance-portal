import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import io
import calendar
from datetime import datetime, timedelta

# --- 1. CONFIG & SYSTEM CSS ---
st.set_page_config(page_title="NBH Workforce Portal", layout="wide")

st.markdown("""
    <style>
    .nbh-cal-container {
        display: grid; grid-template-columns: repeat(7, 1fr);
        width: 100%; border-top: 1px solid #e0e0e0; border-left: 1px solid #e0e0e0;
        background-color: white; margin-bottom: 20px;
    }
    .nbh-cal-header {
        text-align: center; padding: 12px; font-weight: 500; color: #888;
        border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0;
        background-color: #F8F9FA; text-transform: uppercase; font-size: 12px;
    }
    .nbh-cal-day {
        min-height: 140px; border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0;
        padding: 10px; position: relative; background-color: white;
        display: flex; flex-direction: column; align-items: center;
    }
    .nbh-padding-day { background-color: #fcfcfc; color: #ccc !important; }
    .nbh-weekly-off {
        background: repeating-linear-gradient(45deg, #ffffff, #ffffff 10px, #f5f5f5 10px, #f5f5f5 20px) !important;
    }
    .nbh-day-num { font-size: 14px; color: #666; font-weight: bold; align-self: flex-start; margin-bottom: 5px;}
    .nbh-today-circle {
        background-color: #5D5FEF; color: white !important;
        border-radius: 50%; display: inline-block; width: 24px; height: 24px;
        text-align: center; line-height: 24px;
    }
    .nbh-status-box { text-align: center; margin: auto 0; }
    .nbh-status-icon { font-size: 20px; display: block; margin-bottom: 2px; }
    .nbh-status-label { font-size: 10px; font-weight: bold; text-transform: uppercase; display: block; }
    .nbh-time-text { font-size: 11px; font-weight: 800; color: #333; margin-top: 2px; }
    .nbh-shift-footer { position: absolute; bottom: 8px; font-size: 9px; color: #999; text-align: center; width: 100%; }
    .nbh-off-label { margin: auto; font-size: 10px; color: #bbb; font-weight: bold; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

def make_hash(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db(): return sqlite3.connect('societies.db', check_same_thread=False)

def format_pretty_time(decimal_hours):
    if decimal_hours == 0: return "0h 0m"
    hours = int(decimal_hours)
    minutes = int(round((decimal_hours - hours) * 60))
    return f"{hours}h {minutes}m"

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00"]: return 0.0
    try:
        if isinstance(t, (int, float)): return float(t)
        p = str(t).split(':')
        return int(p[0]) + (int(p[1])/60.0)
    except: return 0.0

# --- 2. AUTHENTICATION & STATE GUARD ---
if 'auth' not in st.session_state: st.session_state.auth = {'logged_in': False}

# STATE GUARD: Standardizes columns and prevents KeyError
REQUIRED_COLS = ['Name', 'Category', 'Date', 'In', 'Out', 'Worked_Hrs', 'Status']
if 'processed_data' in st.session_state:
    if not all(col in st.session_state.processed_data.columns for col in REQUIRED_COLS):
        st.session_state.pop('processed_data', None)

if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood Login")
    with st.form("login"):
        e = st.text_input("Email"); p = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            conn = get_db()
            user = pd.read_sql(f"SELECT * FROM users WHERE email='{e}'", conn)
            conn.close()
            if not user.empty and make_hash(p) == user.iloc[0]['password']:
                st.session_state.auth = {'logged_in': True, 'user': e, 'name': user.iloc[0]['society_name']}
                st.rerun()
            else: st.error("❌ Invalid Login")
else:
    user_email = st.session_state.auth['user']
    full_name = st.session_state.auth['name']

    st.sidebar.title(f"👋 {full_name}")
    page = st.sidebar.radio("Navigate", ["🚀 Attendance Dashboard", "👥 Roster Setup", "📅 Holiday Calendar"])
    if st.sidebar.button("Logout"):
        st.session_state.auth = {'logged_in': False}
        st.session_state.pop('processed_data', None)
        st.rerun()

    # --- PAGE: HOLIDAYS ---
    if page == "📅 Holiday Calendar":
        st.header("Public Holiday Planner")
        conn = get_db(); u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{user_email}'", conn).iloc[0]; conn.close()
        saved_hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
        cy, cm = st.columns(2); year = cy.selectbox("Year", [2024, 2025, 2026])
        m_name = cm.selectbox("Month", list(calendar.month_name)[1:], index=datetime.now().month-1)
        m_num = list(calendar.month_name).index(m_name); calendar.setfirstweekday(calendar.SUNDAY)
        cal_matrix = calendar.monthcalendar(year, m_num); weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        st.write(f"### {m_name} {year}")
        new_selections = []
        for week in cal_matrix:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day != 0:
                    d_str = f"{year}-{m_num:02d}-{day:02d}"
                    if cols[i].checkbox(f"{day} ({weekdays[i]})", value=d_str in saved_hols, key=f"hp_{d_str}"):
                        new_selections.append(d_str)
        if st.button("💾 Save Holidays"):
            other_hols = [h for h in saved_hols if not h.startswith(f"{year}-{m_num:02d}")]
            conn = get_db(); conn.execute('UPDATE users SET holidays=? WHERE email=?', (",".join(list(set(other_hols + new_selections))), user_email))
            conn.commit(); conn.close(); st.success("Holidays Updated!")

    # --- PAGE: ROSTER ---
    elif page == "👥 Roster Setup":
        st.header("Individual Roster Management")
        conn = get_db(); roster_df = pd.read_sql(f"SELECT employee_name as 'Name', category as 'Category', shift_start as 'Shift_Start', shift_hours as 'Shift_Hrs', week_off as 'Week_Off' FROM rosters WHERE society_email='{user_email}'", conn); conn.close()
        if not roster_df.empty:
            edited_r = st.data_editor(roster_df, use_container_width=True, key="r_ed", 
                                    column_config={"Week_Off": st.column_config.SelectboxColumn("Week Off", options=["None", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])})
            if st.button("💾 Save Roster"):
                conn = get_db()
                for _, r in edited_r.iterrows():
                    conn.execute('UPDATE rosters SET shift_hours=?, week_off=?, shift_start=? WHERE employee_name=? AND society_email=?', (r['Shift_Hrs'], r['Week_Off'], r['Shift_Start'], r['Name'], user_email))
                conn.commit(); conn.close(); st.success("Roster Updated!")
        else: st.warning("Upload data in Dashboard first.")

    # --- PAGE: DASHBOARD ---
    elif page == "🚀 Attendance Dashboard":
        st.header("Attendance Analysis & Audit")
        f = st.file_uploader("Upload Attendance CSV", type="csv")
        if f:
            df_raw = pd.read_csv(f); df_raw.columns = [str(c).strip().title() for c in df_raw.columns]
            conn = get_db()
            for _, row in df_raw[['Name', 'Type']].drop_duplicates().iterrows():
                if not conn.execute('SELECT 1 FROM rosters WHERE employee_name=? AND society_email=?', (row['Name'], user_email)).fetchone():
                    conn.execute('INSERT INTO rosters (society_email, employee_name, category, shift_hours, week_off, shift_start) VALUES (?,?,?,8.0,"Sunday", "09:00 AM")', (user_email, row['Name'], row['Type']))
            conn.commit(); conn.close()
            
            if st.button("🚀 Process & Generate Summary"):
                conn = get_db(); rost = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{user_email}'", conn).set_index('employee_name').to_dict('index')
                u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{user_email}'", conn).iloc[0]; conn.close()
                hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
                date_cols = [col.split(' ')[0] for col in df_raw.columns if 'Duration' in col]
                
                final_rows = []
                for _, row in df_raw.iterrows():
                    name = row['Name']; emp_r = rost.get(name, {'shift_hours': 8.0, 'week_off': 'Sunday', 'category': 'General', 'shift_start': '09:00 AM'})
                    for d in date_cols:
                        hrs = time_to_decimal(row.get(f"{d} Duration", 0))
                        # Explicitly mapping column names
                        in_t = str(row.get(f"{d} Check In", "00:00"))
                        out_t = str(row.get(f"{d} Check Out", "00:00"))
                        
                        dt = pd.to_datetime(d)
                        if hrs >= emp_r['shift_hours']: s = "Present"
                        elif hrs >= (emp_r['shift_hours']/2): s = "Half Day"
                        elif d in hols: s = "Holiday"
                        elif dt.strftime('%A') == emp_r['week_off']: s = "Weekly Off"
                        else: s = "Absent"
                        
                        final_rows.append({
                            "Month": dt.strftime('%B %Y'), "Name": name, 
                            "Category": emp_r['category'], "Date": d, 
                            "In": in_t, "Out": out_t, "Worked_Hrs": hrs, "Status": s
                        })
                st.session_state.processed_data = pd.DataFrame(final_rows)

        if 'processed_data' in st.session_state:
            data = st.session_state.processed_data
            sel_month = st.selectbox("Select Month", data['Month'].unique())
            m_data = data[data['Month'] == sel_month]
            
            # --- THE AUDIT TABLE (Now standard names) ---
            st.subheader("📑 Monthly Detailed Audit Log (All Employees)")
            audit_view = m_data[['Name', 'Category', 'Date', 'In', 'Out', 'Worked_Hrs', 'Status']].copy()
            audit_view['Worked_Hrs'] = audit_view['Worked_Hrs'].apply(format_pretty_time)
            st.dataframe(audit_view, use_container_width=True, hide_index=True)

            st.divider()
            st.header("👤 Individual Spotlight")
            sel_name = st.selectbox("Select Employee for Calendar", m_data['Name'].unique())
            p_df = data[(data['Name'] == sel_name) & (data['Month'] == sel_month)].sort_values('Date')

            # --- BUILD HTML CALENDAR ---
            html = ["<div class='nbh-cal-container'>"]
            for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]: html.append(f"<div class='nbh-cal-header'>{d}</div>")
            
            f_day = pd.to_datetime(p_df['Date'].min()); padding = (f_day.weekday() + 1) % 7
            prev_day = f_day - timedelta(days=padding)
            for _ in range(padding): 
                html.append(f"<div class='nbh-cal-day nbh-padding-day'><span class='nbh-day-num'>{prev_day.day}</span></div>")
                prev_day += timedelta(days=1)
            
            mapping = {"Present": ("🟢", "#2E7D32"), "Absent": ("🔴", "#D32F2F"), "Half Day": ("🌓", "#F9A825"), "Holiday": ("🏖️", "#1565C0"), "Weekly Off": ("ⓧ", "#999")}
            today_num = datetime.now().day if datetime.now().strftime('%B %Y') == sel_month else -1
            
            for _, r in p_df.iterrows():
                is_off = "nbh-weekly-off" if r['Status'] == "Weekly Off" else ""
                icon, color = mapping.get(r['Status'], ("❓", "#000"))
                today_cls = "nbh-today-circle" if pd.to_datetime(r['Date']).day == today_num else ""
                
                if is_off:
                    body = f"<div class='nbh-off-label'>{icon} {r['Status']}</div>"
                else:
                    body = f"<div class='nbh-status-box'><span class='nbh-status-icon'>{icon}</span><span class='nbh-status-label' style='color:{color};'>{r['Status']}</span><span class='nbh-time-text'>{format_pretty_time(r['Worked_Hrs'])}</span></div>"
                
                html.append(f"""
                <div class="nbh-cal-day {is_off}">
                    <span class="nbh-day-num"><span class="{today_cls}">{pd.to_datetime(r['Date']).day}</span></span>
                    {body}
                    <div class="nbh-shift-footer">{r['In']} - {r['Out']}</div>
                </div>""")
            html.append("</div>")
            st.markdown("".join(html), unsafe_allow_html=True)
