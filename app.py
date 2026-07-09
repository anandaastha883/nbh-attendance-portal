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
        text-align: center; padding: 10px; font-weight: bold; color: #888;
        border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0;
        background-color: #F8F9FA; text-transform: uppercase; font-size: 12px;
    }
    .nbh-cal-day {
        min-height: 100px; border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0;
        padding: 8px; position: relative; background-color: white;
    }
    .nbh-padding-day { color: #ccc !important; background-color: #fafafa; }
    .nbh-weekly-off {
        background: repeating-linear-gradient(45deg, #ffffff, #ffffff 10px, #f5f5f5 10px, #f5f5f5 20px) !important;
    }
    .nbh-day-num { font-size: 14px; color: #666; font-weight: bold; }
    .nbh-today-circle {
        background-color: #5D5FEF; color: white !important;
        border-radius: 50%; display: inline-block; width: 22px; height: 22px;
        text-align: center; line-height: 22px;
    }
    .nbh-status-box { text-align: center; margin-top: 10px; }
    .nbh-status-label { font-size: 10px; font-weight: bold; text-transform: uppercase; display: block; }
    .nbh-shift-time { position: absolute; bottom: 8px; left: 8px; font-size: 9px; color: #999; }
    .nbh-off-label {
        position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
        font-size: 10px; color: #999; font-weight: bold; text-align: center;
    }
    /* Holiday Picker Styling */
    .holiday-pick-box {
        border: 1px solid #eee; padding: 10px; border-radius: 5px; text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

def make_hash(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db(): return sqlite3.connect('societies.db', check_same_thread=False)

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00"]: return 0.0
    try:
        if isinstance(t, (int, float)): return float(t)
        p = str(t).split(':')
        return int(p[0]) + (int(p[1])/60.0)
    except: return 0.0

# --- 2. AUTHENTICATION ---
if 'auth' not in st.session_state: st.session_state.auth = {'logged_in': False}

if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood Society Portal")
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

    t1, t2, t3 = st.tabs(["🚀 Dashboard", "👥 Roster Setup", "📅 Holiday Calendar"])

    # --- TAB 3: INTERACTIVE HOLIDAY PICKER ---
    with t3:
        st.header("Exposed Holiday Planner")
        st.info("Select a month and click the checkboxes to mark Public Holidays.")
        
        conn = get_db(); u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{user_email}'", conn).iloc[0]; conn.close()
        saved_hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]

        col_y, col_m = st.columns(2)
        year = col_y.selectbox("Year", [2024, 2025, 2026], index=0)
        month_name = col_m.selectbox("Month", list(calendar.month_name)[1:], index=datetime.now().month-1)
        month_num = list(calendar.month_name).index(month_name)

        # Create the Calendar Grid for Selection
        cal = calendar.monthcalendar(year, month_num)
        weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        
        # Note: calendar module starts week on Mon (0) or configured. We want Sun-Sat.
        calendar.setfirstweekday(calendar.SUNDAY)
        cal = calendar.monthcalendar(year, month_num)

        st.write(f"### {month_name} {year}")
        new_selections = []
        
        # Draw the selection grid
        for week in cal:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day == 0:
                    cols[i].write("")
                else:
                    date_str = f"{year}-{month_num:02d}-{day:02d}"
                    is_checked = date_str in saved_hols
                    # Unique key for every checkbox
                    val = cols[i].checkbox(f"{day} {weekdays[i]}", value=is_checked, key=f"hp_{date_str}")
                    if val: new_selections.append(date_str)

        if st.button("💾 Save All Holidays"):
            # We must preserve holidays from OTHER months too
            other_month_hols = [h for h in saved_hols if not h.startswith(f"{year}-{month_num:02d}")]
            final_hols = list(set(other_month_hols + new_selections))
            conn = get_db(); conn.execute('UPDATE users SET holidays=? WHERE email=?', (",".join(final_hols), user_email))
            conn.commit(); conn.close(); st.success("Holiday Calendar Updated!")

    # --- TAB 2: ROSTER ---
    with t2:
        st.header("Individual Roster Management")
        conn = get_db(); roster_df = pd.read_sql(f"SELECT employee_name as 'Name', category as 'Category', shift_hours as 'Shift_Hrs', week_off as 'Week_Off' FROM rosters WHERE society_email='{user_email}'", conn); conn.close()
        if not roster_df.empty:
            edited_r = st.data_editor(roster_df, use_container_width=True, key="r_ed", column_config={"Week_Off": st.column_config.SelectboxColumn("Week Off", options=["None", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])})
            if st.button("💾 Save Roster Changes"):
                conn = get_db()
                for _, r in edited_r.iterrows():
                    conn.execute('UPDATE rosters SET shift_hours=?, week_off=? WHERE employee_name=? AND society_email=?', (r['Shift_Hrs'], r['Week_Off'], r['Name'], user_email))
                conn.commit(); conn.close(); st.success("Roster Updated!")

    # --- TAB 1: DASHBOARD ---
    with t1:
        f = st.file_uploader("Upload Attendance Dump", type="csv")
        if f:
            df_raw = pd.read_csv(f); df_raw.columns = [c.strip().title() for c in df_raw.columns]
            conn = get_db()
            for _, row in df_raw[['Name', 'Type']].drop_duplicates().iterrows():
                if not conn.execute('SELECT 1 FROM rosters WHERE employee_name=? AND society_email=?', (row['Name'], user_email)).fetchone():
                    conn.execute('INSERT INTO rosters (society_email, employee_name, category, shift_hours, week_off) VALUES (?,?,?,8.0,"Sunday")', (user_email, row['Name'], row['Type']))
            conn.commit(); conn.close()
            
            if st.button("🚀 Run Analysis"):
                conn = get_db(); rost = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{user_email}'", conn).set_index('employee_name').to_dict('index'); u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{user_email}'", conn).iloc[0]; conn.close()
                hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
                date_cols = [col.split(' ')[0] for col in df_raw.columns if 'Duration' in col]
                tidy = []
                for _, row in df_raw.iterrows():
                    name = row['Name']; r_logic = rost.get(name, {'shift_hours': 8.0, 'week_off': 'Sunday', 'category': 'General'})
                    for d in date_cols:
                        hrs = time_to_decimal(row.get(f"{d} Duration", 0))
                        dt = pd.to_datetime(d)
                        if hrs >= r_logic['shift_hours']: s = "Present"
                        elif hrs >= (r_logic['shift_hours']/2): s = "Half Day"
                        elif d in hols: s = "Holiday"
                        elif dt.strftime('%A') == r_logic['week_off']: s = "Weekly Off"
                        else: s = "Absent"
                        tidy.append({"Month": dt.strftime('%B %Y'), "Name": name, "Category": r_logic['category'], "Date": d, "Hrs": hrs, "Status": s, "In": str(row.get(f"{d} Check In", "09:30")), "Out": str(row.get(f"{d} Check Out", "18:30"))})
                st.session_state.master_data = pd.DataFrame(tidy)

        if 'master_data' in st.session_state:
            data = st.session_state.master_data
            st.header("📊 Society Summary")
            sel_month = st.selectbox("Select Month", data['Month'].unique().tolist())
            m_data = data[data['Month'] == sel_month]
            st.dataframe(m_data.groupby(['Name', 'Category', 'Status']).size().unstack(fill_value=0).reset_index(), use_container_width=True)

            st.divider()
            st.header("👤 Individual Spotlight")
            sel_name = st.selectbox("Select Employee", m_data['Name'].unique())
            p_df = data[(data['Name'] == sel_name) & (data['Month'] == sel_month)].sort_values('Date')

            # Build Calendar
            html_parts = ["<div class='nbh-cal-container'>"]
            for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]: html_parts.append(f"<div class='nbh-cal-header'>{d}</div>")
            
            first_day = pd.to_datetime(p_df['Date'].min())
            padding = (first_day.weekday() + 1) % 7
            for _ in range(padding): html_parts.append("<div class='nbh-cal-day nbh-padding-day'></div>")
            
            today_num = datetime.now().day if datetime.now().strftime('%B %Y') == sel_month else -1
            for _, r in p_df.iterrows():
                d_obj = pd.to_datetime(r['Date'])
                is_off = "nbh-weekly-off" if r['Status'] == "Weekly Off" else ""
                today_class = "nbh-today-circle" if d_obj.day == today_num else ""
                mapping = {"Present": ("🟢", "#2E7D32"), "Absent": ("🔴", "#D32F2F"), "Half Day": ("🌓", "#F9A825"), "Holiday": ("🏖️", "#1565C0"), "Weekly Off": ("ⓧ", "#999")}
                icon, color = mapping.get(r['Status'], ("❓", "#000"))
                
                body = f"<div class='nbh-off-label'>{icon} {r['Status']}</div>" if is_off else f"<div class='nbh-status-box'><span class='nbh-status-icon'>{icon}</span><span class='nbh-status-label' style='color:{color};'>{r['Status']}</span></div>"
                html_parts.append(f"<div class='nbh-cal-day {is_off}'><span class='nbh-day-num {today_class}'>{d_obj.day}</span>{body}<span class='nbh-shift-time'>{r['In']} - {r['Out']}</span></div>")
            
            html_parts.append("</div>")
            st.markdown("".join(html_parts), unsafe_allow_html=True)
            
    if st.sidebar.button("🚪 Logout"): st.session_state.auth = {'logged_in': False}; st.rerun()
