import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import io
import calendar
import xlsxwriter
from fpdf import FPDF
from datetime import datetime, timedelta

# --- 1. CONFIG & SYSTEM CSS ---
st.set_page_config(page_title="NBH Enterprise HRMS", layout="wide")

st.markdown("""
    <style>
    .nbh-cal-container { display: grid; grid-template-columns: repeat(7, 1fr); width: 100%; border-top: 1px solid #e0e0e0; border-left: 1px solid #e0e0e0; background-color: white; margin-bottom: 20px; }
    .nbh-cal-header { text-align: center; padding: 12px; font-weight: 500; color: #888; border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0; background-color: #F8F9FA; text-transform: uppercase; font-size: 12px; }
    .nbh-cal-day { min-height: 140px; border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0; padding: 10px; position: relative; background-color: white; display: flex; flex-direction: column; align-items: center; }
    .nbh-padding-day { background-color: #fcfcfc; color: #ccc !important; }
    .nbh-weekly-off { background: repeating-linear-gradient(45deg, #ffffff, #ffffff 10px, #f2f2f2 10px, #f2f2f2 20px) !important; }
    .nbh-day-num { font-size: 14px; color: #666; font-weight: bold; align-self: flex-start; margin-bottom: 5px;}
    .nbh-today-circle { background-color: #5D5FEF; color: white !important; border-radius: 50%; display: inline-block; width: 22px; height: 22px; text-align: center; line-height: 22px; }
    .nbh-status-box { text-align: center; margin: auto 0; }
    .nbh-status-icon { font-size: 20px; display: block; margin-bottom: 2px; }
    .nbh-status-label { font-size: 10px; font-weight: bold; text-transform: uppercase; display: block; }
    .nbh-time-text { font-size: 11px; font-weight: 800; color: #333; margin-top: 4px; display: block; }
    .nbh-shift-footer { position: absolute; bottom: 8px; font-size: 9px; color: #999; text-align: center; width: 100%; }
    .nbh-off-label { margin: auto; font-size: 10px; color: #aaa; font-weight: bold; text-align: center; }
    .manpower-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #5D5FEF; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CORE HELPERS ---
def make_hash(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db(): return sqlite3.connect('societies.db', check_same_thread=False)
def format_curr(v): return f"₹{v:,.2f}"
def format_pretty_time(decimal_hours):
    if decimal_hours == 0: return ""
    h, m = int(decimal_hours), int(round((decimal_hours - int(decimal_hours)) * 60))
    return f"{h}h {m}m"

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00"]: return 0.0
    try:
        if isinstance(t, (int, float)): return float(t)
        p = str(t).split(':')
        return int(p[0]) + (int(p[1])/60.0)
    except: return 0.0

# --- 3. REPORT ENGINES ---
def generate_master_excel(full_data, pay_df, month):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pay_df.to_excel(writer, sheet_name='Payroll_Summary', index=False)
        full_data.to_excel(writer, sheet_name='Detailed_Logs', index=False)
        workbook = writer.book
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
        for sn in ['Payroll_Summary', 'Detailed_Logs']:
            ws = writer.sheets[sn]; ws.set_column('A:Z', 18)
            current_cols = pay_df.columns if sn == 'Payroll_Summary' else full_data.columns
            for i, col in enumerate(current_cols): ws.write(0, i, col, header_fmt)
    return output.getvalue()

def generate_slip_pdf(soc, month, name, p_df, net_val):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 16); pdf.cell(190, 10, f"{soc}", 0, 1, "C")
    pdf.set_font("Arial", "", 12); pdf.cell(190, 10, f"Salary Slip: {month}", 0, 1, "C"); pdf.ln(10)
    pdf.set_font("Arial", "B", 11); pdf.cell(190, 10, f"Name: {name}", 0, 1); pdf.set_font("Arial", "B", 10); pdf.cell(190, 10, f"Final Net Pay: Rs. {net_val}", 1, 1); pdf.ln(5)
    pdf.set_font("Arial", "B", 8); cols = ["Date", "Status", "Hours"]; w = [40, 70, 40]
    for i, h in enumerate(cols): pdf.cell(w[i], 10, h, 1)
    pdf.ln(); pdf.set_font("Arial", "", 8)
    for _, r in p_df.iterrows():
        pdf.cell(w[0], 10, str(r['Date']), 1); pdf.cell(w[1], 10, str(r['Status']), 1); pdf.cell(w[2], 10, format_pretty_time(r['Worked_Hrs']), 1); pdf.ln()
    return bytes(pdf.output())

# --- 4. AUTH & SESSION ---
if 'auth' not in st.session_state: st.session_state.auth = {'logged_in': False}

# Emergency cleanup to prevent KeyError from old schemas
if 'processed_data' in st.session_state:
    if 'Punctuality' not in st.session_state.processed_data.columns:
        st.session_state.pop('processed_data', None)

if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood Admin Login")
    t_m, t_a = st.tabs(["🏠 Society Manager", "🔑 NBH Admin"])
    with t_m:
        with st.form("m_login"):
            me = st.text_input("Society Email"); mp = st.text_input("Password", type="password")
            if st.form_submit_button("Manager Login"):
                conn = get_db(); user = pd.read_sql(f"SELECT * FROM users WHERE email='{me}'", conn); conn.close()
                if not user.empty and user.iloc[0]['password'] == make_hash(mp):
                    st.session_state.auth = {'logged_in': True, 'user': me, 'name': user.iloc[0]['society_name'], 'role': 'manager'}
                    st.session_state.pop('processed_data', None); st.rerun()
                else: st.error("❌ Invalid Login")
    with t_a:
        with st.form("a_login"):
            ae = st.text_input("Admin Username"); ap = st.text_input("Admin Password", type="password")
            if st.form_submit_button("Admin Login"):
                conn = get_db(); user = pd.read_sql(f"SELECT * FROM users WHERE email='{ae}'", conn); conn.close()
                if not user.empty and user.iloc[0]['password'] == make_hash(ap) and user.iloc[0]['role'] == 'super_admin':
                    st.session_state.auth = {'logged_in': True, 'user': ae, 'name': 'NBH Admin', 'role': 'super_admin'}; st.rerun()
                else: st.error("❌ Invalid Admin Credentials")
else:
    u_email, u_name, u_role = st.session_state.auth['user'], st.session_state.auth['name'], st.session_state.auth['role']
    st.sidebar.title(f"👋 {u_name}")
    if st.sidebar.button("Logout"): st.session_state.auth = {'logged_in': False}; st.rerun()

    if u_role == 'super_admin':
        st.header("🔑 Master Admin Console")
        conn = get_db(); all_socs = pd.read_sql("SELECT society_name as 'Society', email as 'Account' FROM users WHERE role='manager'", conn); conn.close()
        st.dataframe(all_socs, use_container_width=True)
        with st.form("add_soc"):
            st.subheader("➕ Register New Society"); n, e, p = st.text_input("Name"), st.text_input("Email"), st.text_input("Password")
            if st.form_submit_button("Create Account"):
                try: 
                    conn = get_db(); conn.execute("INSERT INTO users (email,password,society_name,role) VALUES (?,?,?,?)",(e,make_hash(p),n,'manager'))
                    conn.commit(); conn.close(); st.success("Added!"); st.rerun()
                except: st.error("Email taken.")
    else:
        page = st.sidebar.radio("Navigate", ["🚀 Attendance Dashboard", "💰 Payroll Hub", "👥 Employee Configuration", "📅 Holiday Planner"])

        if page == "📅 Holiday Planner":
            st.header("Holiday Planner")
            conn = get_db(); u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{u_email}'", conn).iloc[0]; conn.close(); saved = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
            y = st.selectbox("Year", [2024,2025,2026]); m_name = st.selectbox("Month", list(calendar.month_name)[1:], index=datetime.now().month-1); m_num = list(calendar.month_name).index(m_name); calendar.setfirstweekday(calendar.SUNDAY); cal_matrix = calendar.monthcalendar(y, m_num); weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            new_selections = []
            for week in cal_matrix:
                cols = st.columns(7)
                for i, day in enumerate(week):
                    if day != 0:
                        d_str = f"{y}-{m_num:02d}-{day:02d}"
                        if cols[i].checkbox(f"{day} ({weekdays[i]})", value=d_str in saved, key=f"hp_{d_str}"): new_selections.append(d_str)
            if st.button("💾 Save"):
                other = [h for h in saved if not h.startswith(f"{y}-{m_num:02d}")]; conn = get_db(); conn.execute('UPDATE users SET holidays=? WHERE email=?', (",".join(list(set(other + new_selections))), u_email)); conn.commit(); conn.close(); st.success("Saved!")

        elif page == "👥 Employee Configuration":
            st.header("Individual Roster & Financial Setup")
            conn = get_db(); roster_df = pd.read_sql(f"""SELECT employee_name as 'Name', category as 'Department', pay_type as 'Salary Type', base_salary as 'Base Pay', ot_rate as 'OT Rate (hr)', late_penalty as 'Late Fee', absent_penalty as 'Absent Fee', half_day_rule as 'Half Day Pay (0.5)', shift_start as 'Start Time', shift_hours as 'Shift Hours', week_off as 'Mandatory Week Off', bonus as 'Bonus', remarks as 'Remarks' FROM rosters WHERE society_email='{u_email}'""", conn); conn.close()
            if not roster_df.empty:
                edited = st.data_editor(roster_df, use_container_width=True, key="config_ed", 
                                        column_config={"Salary Type": st.column_config.SelectboxColumn(options=["Monthly", "Daily"]), "Mandatory Week Off": st.column_config.SelectboxColumn(options=["None", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])}, disabled=["Department"])
                if st.button("💾 Save All Changes"):
                    conn = get_db()
                    for _, r in edited.iterrows(): 
                        conn.execute('''UPDATE rosters SET week_off=?, shift_hours=?, base_salary=?, pay_type=?, ot_rate=?, late_penalty=?, absent_penalty=?, half_day_rule=?, bonus=?, remarks=? WHERE employee_name=? AND society_email=?''', (r['Mandatory Week Off'], r['Shift Hours'], r['Base Pay'], r['Salary Type'], r['OT Rate (hr)'], r['Late Fee'], r['Absent Fee'], r['Half Day Pay (0.5)'], r['Bonus'], r['Remarks'], r['Name'], u_email))
                    conn.commit(); conn.close(); st.success("Updated!"); st.rerun()
            else: st.warning("Upload data in Dashboard first.")

        elif page == "💰 Payroll Hub":
            st.header("💰 Society Payroll Module")
            if 'processed_data' not in st.session_state: st.warning("Process data in Dashboard first.")
            else:
                data = st.session_state.processed_data; sel_m = st.selectbox("Month", data['Month'].unique()); m_data = data[data['Month'] == sel_m]
                conn = get_db(); rost = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{u_email}'", conn).set_index('employee_name'); conn.close()
                pay_rows = []
                for n in m_data['Name'].unique():
                    if n not in rost.index: continue
                    e_df = m_data[m_data['Name'] == n]; r = rost.loc[n]
                    p, h, w, hl, l, ab = len(e_df[e_df['Status'] == 'Present']), len(e_df[e_df['Status'] == 'Half Day']), len(e_df[e_df['Status'] == 'Weekly Off']), len(e_df[e_df['Status'] == 'Holiday']), len(e_df[e_df['Punctuality'] == 'Late']), len(e_df[e_df['Status'] == 'Absent'])
                    ot_p = round(e_df['OT_Hrs'].sum() * r['ot_rate'], 2); pens = (l * r['late_penalty']) + (ab * r['absent_penalty'])
                    if r['pay_type'] == "Monthly": base = round((r['base_salary'] / 30) * (p + w + hl + (h * r['half_day_rule'])), 2)
                    else: base = round(r['base_salary'] * (p + (h * 0.5)), 2)
                    pay_rows.append({"Employee Name": n, "Salary Type": r['pay_type'], "Base Earned": base, "OT Pay": ot_p, "Total Deductions": pens, "Final Net Payable": round(base + ot_p + r['bonus'] - pens, 2)})
                pay_df = pd.DataFrame(pay_rows); st.dataframe(pay_df, use_container_width=True, hide_index=True)
                col1, col2 = st.columns(2)
                col1.download_button("📥 Master Excel", generate_master_excel(m_data, pay_df, sel_m), f"Payroll_{sel_m}.xlsx")
                worker = st.selectbox("Select Worker for Individual PDF Slip", pay_df['Employee Name'].unique())
                net = pay_df[pay_df['Employee Name']==worker]['Final Net Payable'].iloc[0]
                st.download_button(f"📄 PDF Slip for {worker}", generate_slip_pdf(u_name, sel_m, worker, m_data[m_data['Name']==worker], net), f"Slip_{worker}.pdf", "application/pdf")

        elif page == "🚀 Attendance Dashboard":
            st.header("Attendance Dashboard")
            f = st.file_uploader("Upload CSV", type="csv")
            if f:
                df_raw = pd.read_csv(f); df_raw.columns = [str(c).strip().title() for c in df_raw.columns]
                conn = get_db()
                for _, row in df_raw[['Name', 'Type']].drop_duplicates().iterrows():
                    if not conn.execute('SELECT 1 FROM rosters WHERE employee_name=? AND society_email=?', (row['Name'], u_email)).fetchone():
                        # FIX: This line now saves the real Category (Type) instead of "General"
                        conn.execute('INSERT INTO rosters (society_email, employee_name, category) VALUES (?,?,?)', (u_email, row['Name'], row['Type']))
                conn.commit(); conn.close()
                if st.button("🚀 Process Data"):
                    conn = get_db(); rost_dict = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{u_email}'", conn).set_index('employee_name').to_dict('index')
                    u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{u_email}'", conn).iloc[0]; conn.close(); hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
                    date_cols = [col.split(' ')[0] for col in df_raw.columns if 'Duration' in col]
                    rows = []
                    for _, row in df_raw.iterrows():
                        name = row['Name']; emp = rost_dict.get(name, {'shift_hours': 8.0, 'week_off': 'Sunday', 'category': 'General', 'shift_start': '09:00 AM'})
                        for d in date_cols:
                            h_val = time_to_decimal(row.get(f"{d} Duration", 0)); in_t = str(row.get(f"{d} Check In", "00:00")); out_t = str(row.get(f"{d} Check Out", "00:00"))
                            dt = pd.to_datetime(d)
                            # --- 🧠 THE WEEKLY OFF LOGIC (PRIORITY 1) ---
                            is_off = (dt.strftime('%A').strip().lower() == str(emp['week_off']).strip().lower())
                            if is_off: s = "Weekly Off"
                            elif d in hols: s = "Holiday"
                            elif h_val >= emp['shift_hours']: s = "Present"
                            elif h_val >= (emp['shift_hours']/2): s = "Half Day"
                            else: s = "Absent"
                            
                            is_late = "On-Time"
                            try:
                                act = datetime.strptime(in_t, "%I:%M %p") if " " in in_t else datetime.strptime(in_t, "%H:%M")
                                tgt = datetime.strptime(emp['shift_start'], "%I:%M %p")
                                if act > (tgt + timedelta(minutes=15)): is_late = "Late"
                            except: pass
                            rows.append({"Month": dt.strftime('%B %Y'), "Name": name, "Category": emp['category'], "Date": d, "Worked_Hrs": h_val, "OT_Hrs": max(0, h_val - emp['shift_hours']), "Status": s, "In": in_t, "Out": out_t, "Punctuality": is_late})
                    st.session_state.processed_data = pd.DataFrame(rows)

            if 'processed_data' in st.session_state:
                data = st.session_state.processed_data
                # Manpower Summary
                latest_date = data['Date'].max(); today_df = data[data['Date'] == latest_date]
                conn = get_db(); rost_cnts = pd.read_sql(f"SELECT category, COUNT(*) as total FROM rosters WHERE society_email='{u_email}' GROUP BY category", conn); conn.close()
                st.subheader("📡 Live Manpower Summary (Today)")
                m_cols = st.columns(max(len(rost_cnts), 1))
                for i, (_, r_cnt) in enumerate(rost_cnts.iterrows()):
                    pres = len(today_df[(today_df['Category'] == r_cnt['category']) & (today_df['Status'] == 'Present')])
                    m_cols[i].markdown(f"<div class='manpower-card'><div style='font-size:12px;'>{r_cnt['category']}</div><div style='font-size:24px;font-weight:bold;'>{pres} / {r_cnt['total']}</div></div>", unsafe_allow_html=True)
                
                st.divider(); col1, col2 = st.columns(2); sel_m = col1.selectbox("Month", data['Month'].unique()); sel_cat = col2.selectbox("Filter Category", ["All"] + data['Category'].unique().tolist())
                m_data = data[data['Month'] == sel_m]
                if sel_cat != "All": m_data = m_data[m_data['Category'] == sel_cat]
                st.subheader("📊 Society Summary Table"); st.dataframe(m_data.groupby(['Name', 'Category', 'Status']).size().unstack(fill_value=0).reset_index(), use_container_width=True)
                sel_n = st.selectbox("Individual Calendar Spotlight", m_data['Name'].unique()); p_df = m_data[m_data['Name'] == sel_n].sort_values('Date')
                
                html = ["<div class='nbh-cal-container'>"]
                for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]: html.append(f"<div class='nbh-cal-header'>{d}</div>")
                f_day = pd.to_datetime(p_df['Date'].min()); padding = (f_day.weekday() + 1) % 7
                for _ in range(padding): html.append("<div class='nbh-cal-day nbh-padding-day'></div>")
                mapping = {"Present": ("🟢", "#2E7D32"), "Absent": ("🔴", "#D32F2F"), "Half Day": ("🌓", "#F9A825"), "Holiday": ("🏖️", "#1565C0"), "Weekly Off": ("ⓧ", "#999")}
                for _, r in p_df.iterrows():
                    is_off = "nbh-weekly-off" if r['Status'] == "Weekly Off" else ""
                    icon, color = mapping.get(r['Status'], ("❓", "#000"))
                    t_info = f"<span class='nbh-time-text'>{format_pretty_time(r['Worked_Hrs'])}</span>" if r['Worked_Hrs'] > 0 else ""
                    body = f"<div class='nbh-off-label'>{icon} Weekly Off</div>{t_info}" if r['Status'] == "Weekly Off" else f"<div class='nbh-status-box'><span class='nbh-status-icon'>{icon}</span><span class='nbh-status-label' style='color:{color};'>{r['Status']}</span>{t_info}</div>"
                    html.append(f'<div class="nbh-cal-day {is_off}"><span class="nbh-day-num">{pd.to_datetime(r["Date"]).day}</span>{body}<div class="nbh-shift-footer">{r["In"]} - {r["Out"]}</div></div>')
                st.markdown("".join(html) + "</div>", unsafe_allow_html=True)
