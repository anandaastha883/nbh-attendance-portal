import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import io
import calendar
import re
from fpdf import FPDF
from datetime import datetime, timedelta

# --- 1. CONFIG & SYSTEM CSS ---
st.set_page_config(page_title="NBH Workforce Enterprise", layout="wide")

st.markdown("""
    <style>
    html, body, [class*="st-"] { font-family: "Source Sans Pro", sans-serif; }
    [data-testid="stFileUploader"] section label { display: none !important; }
    [data-testid="stFileUploader"] { padding-top: 10px; }
    [data-testid="stIconMaterial"] { font-size: 0 !important; visibility: hidden !important; }
    [data-testid="stFileUploaderDropzoneInstructions"]::before { content: "📂 "; font-size: 24px; }

    /* CALENDAR STYLING */
    .nbh-cal-container { display: grid; grid-template-columns: repeat(7, 1fr); width: 100%; border: 1px solid #ddd; background-color: #eee; gap: 1px; margin-top:20px;}
    .nbh-cal-header { background-color: #5D5FEF !important; text-align: center; padding: 12px; font-weight: 800; color: white !important; font-size: 14px; text-transform: uppercase; border: 1px solid #4a4cd1; }
    .nbh-cal-day { min-height: 165px; background-color: white; padding: 10px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; position: relative; border-right: 1px solid #ddd; border-bottom: 1px solid #ddd;}
    .nbh-weekly-off { background: repeating-linear-gradient(45deg, #ffffff, #ffffff 10px, #f9f9f9 10px, #f9f9f9 20px) !important; }
    .nbh-day-num-row { display: flex; align-items: baseline; gap: 6px; align-self: flex-start; margin-bottom: 5px; }
    .nbh-day-num { font-size: 16px; color: #333; font-weight: bold; }
    .nbh-weekday-tag { font-size: 10px; color: #999; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
    .nbh-status-icon { font-size: 24px; display: block; margin-top: 2px; }
    .nbh-status-label { font-size: 10px; font-weight: 900; text-transform: uppercase; margin-top: 4px; }
    .nbh-time-text { font-size: 11px; font-weight: 800; color: #1B2132; margin-top: 4px; background-color: #f0f1fd; padding: 2px 8px; border-radius: 10px; border: 1px solid #d1d4f9; }
    .nbh-shift-footer { margin-top: auto; padding-top: 4px; border-top: 1px solid #f0f0f0; font-size: 10px; color: #666; font-weight: 600; text-align: center; width: 100%; }
    .nbh-manpower-tag { font-size: 9px; color: #5D5FEF; font-weight: 800; margin-top: 2px; text-transform: uppercase; background: #eeefff; padding: 1px 5px; border-radius: 4px; }

    /* CARDS STYLING */
    .manpower-card { background-color: #ffffff; padding: 15px; border-radius: 12px; border: 1px solid #e0e0e0; border-left: 6px solid #5D5FEF; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center;}
    .manpower-label { font-size: 11px; font-weight: 600; color: #888; text-transform: uppercase; }
    .manpower-value { font-size: 18px; font-weight: 700; color: #1B2132; }

    /* ADMIN DASHBOARD HEADER STYLE */
    .card-title-header {
        font-size: 18px;
        font-weight: 700;
        color: #1B2132;
        margin-bottom: 15px;
        border-bottom: 3px solid #5D5FEF;
        padding-bottom: 10px;
        display: block;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CORE HELPERS ---
def make_hash(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db(): return sqlite3.connect('societies.db', check_same_thread=False)
def format_pretty_time(decimal_hours):
    if not decimal_hours or decimal_hours == 0: return ""
    h, m = int(decimal_hours), int(round((decimal_hours - int(decimal_hours)) * 60))
    return f"{h}h {m}m"

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00"]: return 0.0
    try:
        if ":" in str(t):
            parts = str(t).split(':'); return int(parts[0]) + (int(parts[1])/60.0)
        return float(t)
    except: return 0.0

# --- SMART ENGINE ---
_METRIC_PATTERNS = [(re.compile(r'check[\s\-_]*in', re.I), 'Check In'), (re.compile(r'check[\s\-_]*out', re.I), 'Check Out'), (re.compile(r'duration', re.I), 'Duration')]
_ISO_DATE_RE = re.compile(r'^(\d{4})-(\d{1,2})-(\d{1,2})$')

def _parse_date_flexible(text):
    text = text.strip()
    m = _ISO_DATE_RE.match(text)
    if m:
        try: return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except: return None
    for df in (True, False):
        try: return pd.to_datetime(text, dayfirst=df).date()
        except: continue
    return None

def _build_date_column_map(columns):
    date_map = {}
    for col in columns:
        for pattern, key in _METRIC_PATTERNS:
            m = pattern.search(col)
            if m:
                d_obj = _parse_date_flexible(col[:m.start()].strip())
                if d_obj: date_map.setdefault(d_obj, {})[key] = col
    return date_map

# --- 3. PDF ENGINE ---
def generate_pro_pdf(soc, month, name, emp_data, stats, attendance_df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 22); pdf.cell(190, 15, soc, 0, 1, "C")
    pdf.set_font("Arial", "", 14); pdf.cell(190, 10, f"Salary Slip - {month}", 0, 1, "C")
    pdf.ln(5); pdf.set_draw_color(200, 200, 200); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(10)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(95, 8, f"Employee: {name}", 0, 0); pdf.cell(95, 8, f"Dept: {emp_data['category']}", 0, 1)
    pdf.cell(95, 8, f"Wage: {emp_data['pay_type']}", 0, 0); pdf.cell(95, 8, f"Weekly Off: {emp_data['week_off']}", 0, 1); pdf.ln(5)
    pdf.set_fill_color(93, 95, 239); pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 11); pdf.cell(190, 10, "  Attendance Summary", 0, 1, "L", True)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 10)
    pdf.cell(45, 10, f"Presents: {stats['p']}", 0, 0); pdf.cell(45, 10, f"Absents: {stats['ab']}", 0, 0)
    pdf.cell(45, 10, f"Half Days: {stats['h']}", 0, 0); pdf.cell(45, 10, f"Holidays: {stats['hol']}", 0, 1)
    pdf.ln(5); pdf.set_fill_color(46, 125, 50); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 15, f"Net Payable: Rs. {stats['net']}", 0, 1, "C", True)
    pdf.set_text_color(0, 0, 0); pdf.ln(10); pdf.set_font("Arial", "B", 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(60, 10, "Date", 1, 0, "C", True); pdf.cell(80, 10, "Status", 1, 0, "C", True); pdf.cell(50, 10, "Worked Hrs", 1, 1, "C", True)
    pdf.set_font("Arial", "", 9)
    for _, r in attendance_df.iterrows():
        pdf.cell(60, 8, str(r['Date']), 1); pdf.cell(80, 8, str(r['Status']), 1); pdf.cell(50, 8, format_pretty_time(r['Worked_Hrs']), 1); pdf.ln()
    return bytes(pdf.output())

# --- 4. MASTER ENGINE ---
def process_attendance(df_raw, u_email):
    conn = get_db()
    rost_dict = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{u_email}'", conn).set_index('employee_name').to_dict('index')
    u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{u_email}'", conn).iloc[0]
    conn.close()
    hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
    date_map = _build_date_column_map(df_raw.columns)
    if not date_map: return pd.DataFrame()
    sample_date = min(date_map.keys())
    year, month = sample_date.year, sample_date.month
    num_days = calendar.monthrange(year, month)[1]
    all_dates = [datetime(year, month, d).date() for d in range(1, num_days + 1)]
    final_rows = []
    for _, row in df_raw.iterrows():
        name = row['Name']
        emp = rost_dict.get(name, {})
        shift = float(emp.get('shift_hours') or 8.0)
        for d_obj in all_dates:
            d_iso = d_obj.strftime('%Y-%m-%d')
            h_val, in_t, out_t = 0.0, "00:00", "00:00"
            cols = date_map.get(d_obj, {})
            if 'Duration' in cols: h_val = time_to_decimal(row.get(cols['Duration'], 0))
            if 'Check In' in cols: in_t = str(row.get(cols['Check In'], "00:00"))
            if 'Check Out' in cols: out_t = str(row.get(cols['Check Out'], "00:00"))
            is_off = d_obj.strftime('%A') == emp.get('week_off', 'Sunday')
            if d_iso in hols: status = "Holiday"
            elif is_off: status = "Weekly Off"
            elif h_val >= shift: status = "Present"
            elif h_val >= (shift/2) and h_val > 0: status = "Half Day"
            else: status = "Absent"
            final_rows.append({"Month": sample_date.strftime('%B %Y'), "Name": name, "Category": emp.get('category') or row['Type'], "Date": d_iso, "Worked_Hrs": h_val, "Status": status, "In": in_t, "Out": out_t})
    return pd.DataFrame(final_rows)

# --- 5. UI FLOW ---
if 'auth' not in st.session_state: st.session_state.auth = {'logged_in': False}

if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood Admin Portal")
    t1, t2 = st.tabs(["🏠 Manager Login", "🔐 Admin Login"])
    with t1:
        with st.form("m_log"):
            me, mp = st.text_input("Society Email"), st.text_input("Password", type="password")
            if st.form_submit_button("Manager Login"):
                conn = get_db(); user = pd.read_sql("SELECT * FROM users WHERE email=?", conn, params=(me,))
                if not user.empty and user.iloc[0]['password'] == make_hash(mp):
                    st.session_state.auth = {'logged_in': True, 'user': me, 'name': user.iloc[0]['society_name'], 'role': 'manager'}
                    st.rerun()
                else: st.error("Login Failed")
    with t2:
        with st.form("a_log"):
            ae, ap = st.text_input("Admin Email"), st.text_input("Admin Password", type="password")
            if st.form_submit_button("Admin Sign In"):
                conn = get_db(); user = pd.read_sql("SELECT * FROM users WHERE email=?", conn, params=(ae,))
                if not user.empty and user.iloc[0]['password'] == make_hash(ap) and user.iloc[0]['role'] == 'super_admin':
                    st.session_state.auth = {'logged_in': True, 'user': user.iloc[0]['email'], 'name': 'NBH Admin', 'role': 'super_admin'}
                    st.rerun()
                else: st.error("Login Failed")
else:
    u_email, u_name, u_role = st.session_state.auth['user'], st.session_state.auth['name'], st.session_state.auth['role']
    st.sidebar.title(f"👋 {u_name}")
    if st.sidebar.button("Logout"): st.session_state.auth = {'logged_in': False}; st.rerun()

    # --- SUPER ADMIN DASHBOARD REDESIGNED ---
    if u_role == 'super_admin':
        st.header("🔑 Master Admin Console")
        conn = get_db()
        socs = pd.read_sql("SELECT society_name as Society, email as Account FROM users WHERE role='manager'", conn)
        st.subheader("📋 Registered Societies")
        st.dataframe(socs, use_container_width=True)
        st.divider()

        # Three Equal-Width Cards
        col1, col2, col3 = st.columns(3)
        with col1:
            with st.container(border=True):
                st.markdown('<div class="card-title-header">➕ Register New Society</div>', unsafe_allow_html=True)
                with st.form("reg", clear_on_submit=True):
                    n = st.text_input("Name")
                    e = st.text_input("Email")
                    p = st.text_input("Password", type="password")
                    if st.form_submit_button("Create Account", use_container_width=True):
                        if n and e and p:
                            conn.execute("INSERT OR REPLACE INTO users (email,password,society_name,holidays,role) VALUES (?,?,?,?,?)", (e, make_hash(p), n, '', 'manager'))
                            conn.commit(); st.success("Created!"); st.rerun()
                        else: st.error("All fields required.")
        with col2:
            with st.container(border=True):
                st.markdown('<div class="card-title-header">🔄 Reset Society Password</div>', unsafe_allow_html=True)
                with st.form("reset"):
                    target = st.selectbox("Select Society", socs['Account'].tolist())
                    np = st.text_input("New Password", type="password")
                    cp = st.text_input("Confirm Password", type="password")
                    if st.form_submit_button("Reset Password", use_container_width=True):
                        if np == cp and np:
                            conn.execute("UPDATE users SET password=? WHERE email=?", (make_hash(np), target))
                            conn.commit(); st.success("Updated!")
                        else: st.error("Mismatch or Empty Pass.")
        with col3:
            with st.container(border=True):
                st.markdown('<div class="card-title-header">🗑️ Delete Society</div>', unsafe_allow_html=True)
                with st.form("del"):
                    target_del = st.selectbox("Select Account", ["Select..."] + socs['Account'].tolist())
                    conf = st.checkbox("I confirm permanent deletion")
                    if st.form_submit_button("Remove Permanently", use_container_width=True):
                        if conf and target_del != "Select...":
                            conn.execute("DELETE FROM users WHERE email=?", (target_del,))
                            conn.execute("DELETE FROM rosters WHERE society_email=?", (target_del,))
                            conn.commit(); st.success("Removed!"); st.rerun()
                        else: st.warning("Please confirm deletion.")
        
        st.divider()
        with st.expander("🔐 Change My Own Admin Password"):
            with st.form("admin_self"):
                old = st.text_input("Current Password", type="password")
                new = st.text_input("New Password", type="password")
                if st.form_submit_button("Update Admin Password"):
                    row = pd.read_sql(f"SELECT password FROM users WHERE email='{u_email}'", conn).iloc[0]
                    if make_hash(old) == row['password']:
                        conn.execute("UPDATE users SET password=? WHERE email=?", (make_hash(new), u_email))
                        conn.commit(); st.success("Password Updated!")
                    else: st.error("Current password incorrect.")
        conn.close()

    else:
        # --- MANAGER DASHBOARD (UNCHANGED) ---
        page = st.sidebar.radio("Navigate", ["🚀 Dashboard", "💰 Payroll Hub", "👥 Roster", "📅 Holiday Planner"])
        if page == "🚀 Dashboard":
            st.header(f"👋 Attendance Dashboard")
            f = st.file_uploader("uploader", type="csv")
            if f:
                df_raw = pd.read_csv(f); df_raw.columns = [str(c).strip().title() for c in df_raw.columns]
                conn = get_db()
                for _, r in df_raw[['Name', 'Type']].drop_duplicates().iterrows():
                    conn.execute("INSERT OR IGNORE INTO rosters (society_email, employee_name, category) VALUES (?,?,?)", (u_email, r['Name'], r['Type']))
                conn.commit(); conn.close()
                if st.button("🚀 Analyze Full Month"):
                    st.session_state.processed_data = process_attendance(df_raw, u_email)

            if 'processed_data' in st.session_state:
                data = st.session_state.processed_data
                st.subheader("📡 Live Manpower Summary")
                latest_d = data['Date'].max(); today_df = data[data['Date'] == latest_d]
                conn = get_db(); r_cnts = pd.read_sql(f"SELECT category, COUNT(*) as total FROM rosters WHERE society_email='{u_email}' GROUP BY category", conn); conn.close()
                if not r_cnts.empty:
                    m_cols = st.columns(len(r_cnts))
                    for i, (_, r_cnt) in enumerate(r_cnts.iterrows()):
                        pres = len(today_df[(today_df['Category'] == r_cnt['category']) & (today_df['Status'] == 'Present')])
                        m_cols[i].markdown(f"<div class='manpower-card'><div class='manpower-label'>{r_cnt['category']}</div><div class='manpower-value'>{pres} / {r_cnt['total']}</div></div>", unsafe_allow_html=True)
                st.divider()
                sel_cat = st.selectbox("🎯 Filter by Category", ["All Categories"] + sorted(data['Category'].unique().tolist()))
                filtered = data if sel_cat == "All Categories" else data[data['Category'] == sel_cat]
                st.subheader("📊 Society Summary Table"); st.dataframe(filtered.groupby(['Name', 'Category', 'Status']).size().unstack(fill_value=0).reset_index(), use_container_width=True)
                st.divider(); sel_n = st.selectbox("Individual Spotlight", filtered['Name'].unique())
                p_df = filtered[filtered['Name'] == sel_n].sort_values('Date')
                html = ["<div class='nbh-cal-container'>"]
                for d_name in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]: html.append(f"<div class='nbh-cal-header'>{d_name}</div>")
                f_dt = pd.to_datetime(p_df['Date'].iloc[0]); padding = (f_dt.weekday() + 1) % 7 
                for _ in range(padding): html.append("<div class='nbh-cal-day nbh-padding-day'></div>")
                mapping = {"Present": ("🟢", "#2E7D32"), "Absent": ("🔴", "#D32F2F"), "Half Day": ("🌓", "#F9A825"), "Holiday": ("🏖️", "#1565C0"), "Weekly Off": ("ⓧ", "#999")}
                for _, r in p_df.iterrows():
                    icon, color = mapping.get(r['Status'], ("❓", "#000"))
                    is_off = "nbh-weekly-off" if r['Status'] == "Weekly Off" else ""
                    day_dt = pd.to_datetime(r["Date"])
                    html.append(f'<div class="nbh-cal-day {is_off}"><div class="nbh-day-num-row"><span class="nbh-day-num">{day_dt.day}</span><span class="nbh-weekday-tag">{day_dt.strftime("%a")}</span></div><span class="nbh-status-icon">{icon}</span><span class="nbh-status-label" style="color:{color}">{r["Status"]}</span><span class="nbh-time-text">{format_pretty_time(r["Worked_Hrs"])}</span><div class="nbh-shift-footer">{r["In"]} - {r["Out"]}</div></div>')
                st.markdown("".join(html) + "</div>", unsafe_allow_html=True)
        
        elif page == "💰 Payroll Hub":
            if 'processed_data' in st.session_state:
                data = st.session_state.processed_data; sel_m = st.selectbox("Month", data['Month'].unique())
                m_data = data[data['Month'] == sel_m]; conn = get_db(); rost_df = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{u_email}'", conn); conn.close()
                pay_rows = []
                dim = calendar.monthrange(pd.to_datetime(m_data['Date'].iloc[0]).year, pd.to_datetime(m_data['Date'].iloc[0]).month)[1]
                for n in m_data['Name'].unique():
                    w_df = m_data[m_data['Name'] == n]; r_rows = rost_df[rost_df['employee_name']==n]
                    if r_rows.empty: continue
                    r = r_rows.iloc[0]
                    p, h, ab, w, hol = len(w_df[w_df['Status'] == 'Present']), len(w_df[w_df['Status'] == 'Half Day']), len(w_df[w_df['Status'] == 'Absent']), len(w_df[w_df['Status'] == 'Weekly Off']), len(w_df[w_df['Status'] == 'Holiday'])
                    base_val = float(r['base_salary'])
                    if r['pay_type'] == "Monthly": base = round((base_val/dim)*(p+w+hol+(h*0.5)),2)
                    elif r['pay_type'] == "Daily": base = round(base_val*(p+(h*0.5)),2)
                    else: base = round(base_val*w_df['Worked_Hrs'].sum(),2)
                    pay_rows.append({"Name": n, "p": p, "h": h, "ab": ab, "w": w, "hol": hol, "base": base, "net": round(base - (ab*r['absent_penalty']), 2), "ot_pay": 0, "fine": ab*r['absent_penalty']})
                st.subheader("📋 Master Payroll Summary"); st.dataframe(pd.DataFrame(pay_rows)[["Name", "p", "ab", "net"]].rename(columns={"p":"P","ab":"A","net":"Total"}), use_container_width=True)
                sel_w = st.selectbox("Individual Slip", [x['Name'] for x in pay_rows])
                stats = next(x for x in pay_rows if x['Name'] == sel_w)
                emp_info = rost_df[rost_df['employee_name']==sel_w].iloc[0]
                st.download_button(f"📥 Download Slip for {sel_w}", generate_pro_pdf(u_name, sel_m, sel_w, emp_info, stats, m_data[m_data['Name']==sel_w]), f"Slip_{sel_w}.pdf")
            else: st.warning("Process Dashboard first.")

        elif page == "👥 Roster":
            conn = get_db(); df_r = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{u_email}'", conn); conn.close()
            edited = st.data_editor(df_r, use_container_width=True, hide_index=True, column_config={"pay_type": st.column_config.SelectboxColumn("Wage", options=["Monthly", "Daily", "Hourly"]),"week_off": st.column_config.SelectboxColumn("Off Day", options=["None", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])})
            if st.button("Save"):
                conn = get_db()
                for _, r in edited.iterrows():
                    conn.execute("UPDATE rosters SET pay_type=?, base_salary=?, shift_hours=?, week_off=? WHERE employee_name=? AND society_email=?", (r['pay_type'], r['base_salary'], r['shift_hours'], r['week_off'], r['employee_name'], u_email))
                conn.commit(); conn.close(); st.success("Updated!")
        
        elif page == "📅 Holiday Planner":
            conn = get_db(); u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{u_email}'", conn).iloc[0]; conn.close()
            saved = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
            y = st.selectbox("Year", [2024, 2025, 2026]); m_idx = list(calendar.month_name).index(st.selectbox("Month", list(calendar.month_name)[1:]))
            cal = calendar.monthcalendar(y, m_idx); new_hols = []
            header_cols = st.columns(7)
            for i, wd_name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
                header_cols[i].markdown(f"<div style='text-align:center; font-weight:700; color:#5D5FEF; font-size:12px;'>{wd_name}</div>", unsafe_allow_html=True)
            for week in cal:
                cols = st.columns(7)
                for i, day in enumerate(week):
                    if day != 0:
                        d_str = f"{y}-{m_idx:02d}-{day:02d}"
                        if cols[i].checkbox(str(day), value=d_str in saved, key=d_str): new_hols.append(d_str)
            if st.button("Save"):
                other = [h for h in saved if not h.startswith(f"{y}-{m_idx:02d}")]
                conn = get_db(); conn.execute("UPDATE users SET holidays=? WHERE email=?", (",".join(list(set(other + new_hols))), u_email)); conn.commit(); conn.close(); st.success("Saved!")
