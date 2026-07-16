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
st.set_page_config(page_title="NBH Workforce Enterprise", layout="wide")

st.markdown("""
    <style>
    /* Clean Fonts */
    html, body, [class*="st-"] { font-family: "Source Sans Pro", sans-serif; }

    /* 1. ABSOLUTE FIX FOR "upload upload" */
    [data-testid="stFileUploader"] section label { display: none !important; }
    [data-testid="stFileUploader"] { padding-top: 10px; }

    /* The Material Symbols icon font isn't loading in this environment, so
       Streamlit's built-in icons fall back to showing their raw ligature
       name as plain text everywhere (e.g. "upload", "keyboard_double_arrow_left").
       Hide that raw text globally, then restore a plain-text glyph only for
       the two spots that were visibly broken. */
    [data-testid="stIconMaterial"] { font-size: 0 !important; line-height: 0 !important; }

    [data-testid="stFileUploaderDropzoneInstructions"] [data-testid="stIconMaterial"]::after {
        content: "\\1F4E4";
        font-size: 22px !important;
        line-height: 1 !important;
        display: inline-block;
    }

    [data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"]::after,
    [data-testid="collapsedControl"] [data-testid="stIconMaterial"]::after {
        content: "\\00AB";
        font-size: 18px !important;
        line-height: 1 !important;
        display: inline-block;
    }

    /* 2. CALENDAR STYLING - NO CLASHING */
    .nbh-cal-container { display: grid; grid-template-columns: repeat(7, 1fr); width: 100%; border: 1px solid #ddd; background-color: #eee; gap: 1px; }
    .nbh-cal-header { background-color: #f8f9fa; text-align: center; padding: 12px; font-weight: 700; color: #888; border-right: 1px solid #ddd; border-bottom: 1px solid #ddd; font-size: 11px; }
    .nbh-cal-day { min-height: 150px; background-color: white; padding: 10px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; position: relative; border-right: 1px solid #ddd; border-bottom: 1px solid #ddd;}
    .nbh-weekly-off { background: repeating-linear-gradient(45deg, #ffffff, #ffffff 10px, #f5f5f5 10px, #f5f5f5 20px) !important; }
    .nbh-day-num { font-size: 14px; color: #666; font-weight: bold; align-self: flex-start; margin-bottom: 10px; }
    .nbh-today-circle { background-color: #5D5FEF; color: white !important; border-radius: 50%; padding: 2px 7px; }

    .nbh-status-icon { font-size: 20px; display: block; margin-top: 5px; }
    .nbh-status-box { display: flex; flex-direction: column; align-items: center; }
    .nbh-status-label { font-size: 10px; font-weight: 800; text-transform: uppercase; color: #444; margin-top: 6px; letter-spacing: 0.5px; }
    .nbh-time-text { font-size: 13px; font-weight: 700; color: #1B2132; margin-top: 4px; background-color: #f0f1fd; padding: 2px 10px; border-radius: 10px; display: inline-block; }
    .nbh-shift-footer { margin-top: auto; padding-top: 6px; border-top: 1px solid #f0f0f0; font-size: 10px; color: #888; text-align: center; width: 100%; }
    .nbh-off-label { margin: auto; font-size: 10px; color: #aaa; font-weight: bold; }

    /* 3. MANPOWER CARDS */
    .manpower-card { background-color: #ffffff; padding: 15px; border-radius: 12px; border: 1px solid #e0e0e0; border-left: 6px solid #5D5FEF; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .manpower-label { font-size: 11px; font-weight: 600; color: #888; text-transform: uppercase; }
    .manpower-value { font-size: 20px; font-weight: 700; color: #1B2132; }
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

# Report Engines
def generate_master_excel(full_data, pay_df, month):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pay_df.to_excel(writer, sheet_name='Payroll_Summary', index=False)
        full_data.to_excel(writer, sheet_name='Detailed_Logs', index=False)
        for sn in writer.sheets: writer.sheets[sn].set_column('A:Z', 18)
    return output.getvalue()

def generate_slip_pdf(soc, month, name, emp_info, pay, p_df):
    pdf = FPDF(); pdf.add_page()
    pdf.set_font("Arial", "B", 16); pdf.cell(190, 10, f"{soc}", 0, 1, "C")
    pdf.set_font("Arial", "", 12); pdf.cell(190, 8, f"Salary Slip - {month}", 0, 1, "C")
    pdf.ln(2); pdf.set_draw_color(200, 200, 200); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(6)

    # Employee info
    pdf.set_font("Arial", "B", 11)
    pdf.cell(95, 8, f"Employee Name: {name}", 0, 0)
    pdf.cell(95, 8, f"Department: {emp_info.get('category', '-')}", 0, 1)
    pdf.cell(95, 8, f"Salary Type: {emp_info.get('pay_type', '-')}", 0, 0)
    pdf.cell(95, 8, f"Weekly Off: {emp_info.get('week_off', '-')}", 0, 1)
    pdf.ln(4)

    # Attendance summary
    pdf.set_fill_color(93, 95, 239); pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 11); pdf.cell(190, 8, "Attendance Summary", 0, 1, "L", True)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 10)
    att_rows = [
        ("Present Days", pay['Present']), ("Absent Days", pay['Absent']),
        ("Half Days", pay['Half Day']), ("Holidays", pay['Holiday']),
        ("Weekly Offs", pay['Weekly Off']), ("Late Arrivals", pay['Late Days']),
        ("Total OT Hours", f"{pay['OT Hours']:.2f}"),
    ]
    for i in range(0, len(att_rows), 2):
        left = att_rows[i]
        pdf.set_font("Arial", "B", 10); pdf.cell(45, 7, f"{left[0]}:", 0, 0)
        pdf.set_font("Arial", "", 10); pdf.cell(50, 7, str(left[1]), 0, 0)
        if i + 1 < len(att_rows):
            right = att_rows[i + 1]
            pdf.set_font("Arial", "B", 10); pdf.cell(45, 7, f"{right[0]}:", 0, 0)
            pdf.set_font("Arial", "", 10); pdf.cell(50, 7, str(right[1]), 0, 1)
        else:
            pdf.ln(7)
    pdf.ln(4)

    # Earnings & Deductions
    pdf.set_fill_color(93, 95, 239); pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(95, 8, "Earnings", 0, 0, "L", True); pdf.cell(95, 8, "Deductions", 0, 1, "L", True)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 10)
    earnings = [("Base Earned", pay['Base Earned']), ("OT Pay", pay['OT Pay']), ("Bonus", pay['Bonus'])]
    deductions = [("Late Fee", pay['Late Fee Total']), ("Absent Fee", pay['Absent Fee Total'])]
    for i in range(max(len(earnings), len(deductions))):
        if i < len(earnings):
            pdf.cell(55, 7, earnings[i][0], 0, 0); pdf.cell(40, 7, f"Rs. {earnings[i][1]:,.2f}", 0, 0)
        else:
            pdf.cell(95, 7, "", 0, 0)
        if i < len(deductions):
            pdf.cell(55, 7, deductions[i][0], 0, 0); pdf.cell(40, 7, f"Rs. {deductions[i][1]:,.2f}", 0, 1)
        else:
            pdf.cell(95, 7, "", 0, 1)
    pdf.ln(4)

    # Net payable
    pdf.set_fill_color(46, 125, 50); pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 13)
    pdf.cell(190, 12, f"Net Payable: Rs. {pay['Final Net Payable']:,.2f}", 1, 1, "C", True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    # Daily attendance log
    pdf.set_font("Arial", "B", 11); pdf.cell(190, 8, "Daily Attendance Log", 0, 1)
    pdf.set_font("Arial", "B", 9); pdf.set_fill_color(240, 240, 240)
    headers = ["Date", "Status", "In", "Out", "Hrs"]; widths = [35, 45, 35, 35, 30]
    for hdr, w in zip(headers, widths): pdf.cell(w, 7, hdr, 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 8)
    for _, r in p_df.sort_values('Date').iterrows():
        if pdf.get_y() > 270:
            pdf.add_page()
            pdf.set_font("Arial", "B", 9); pdf.set_fill_color(240, 240, 240)
            for hdr, w in zip(headers, widths): pdf.cell(w, 7, hdr, 1, 0, "C", True)
            pdf.ln(); pdf.set_font("Arial", "", 8)
        pdf.cell(35, 6, str(r['Date']), 1)
        pdf.cell(45, 6, str(r['Status']), 1)
        pdf.cell(35, 6, str(r['In']), 1)
        pdf.cell(35, 6, str(r['Out']), 1)
        pdf.cell(30, 6, f"{r['Worked_Hrs']:.2f}" if r['Worked_Hrs'] else "-", 1)
        pdf.ln()

    return bytes(pdf.output())

# --- 3. AUTH & SESSION ---
if 'auth' not in st.session_state: st.session_state.auth = {'logged_in': False}

def login_logic(email, password, required_role):
    conn = get_db(); user = pd.read_sql(f"SELECT * FROM users WHERE email='{email}'", conn); conn.close()
    if not user.empty and user.iloc[0]['password'] == make_hash(password):
        if user.iloc[0]['role'] == required_role:
            st.session_state.auth = {'logged_in': True, 'user': email, 'name': user.iloc[0]['society_name'], 'role': user.iloc[0]['role']}
            st.session_state.pop('processed_data', None); return True
    st.error(f"❌ Access Denied for {required_role}")
    return False

# --- 4. UI FLOW ---
if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood Management Portal")
    t_m, t_a = st.tabs(["🏠 Society Manager", "🔐 System Admin"])
    with t_m:
        with st.form("m_login"):
            me = st.text_input("Society Email"); mp = st.text_input("Password", type="password")
            if st.form_submit_button("Manager Login"):
                if login_logic(me, mp, 'manager'): st.rerun()
    with t_a:
        with st.form("a_login"):
            ae = st.text_input("Admin Email"); ap = st.text_input("Admin Password", type="password")
            if st.form_submit_button("Admin Login"):
                if login_logic(ae, ap, 'super_admin'): st.rerun()
else:
    u_email, u_name, u_role = st.session_state.auth['user'], st.session_state.auth['name'], st.session_state.auth['role']
    st.sidebar.title(f"👋 {u_name}")
    if st.sidebar.button("Logout"): st.session_state.auth = {'logged_in': False}; st.rerun()

    # --- IF ADMIN ---
    if u_role == 'super_admin':
        st.header("🔑 Master Admin Console")
        conn = get_db(); all_socs = pd.read_sql("SELECT society_name as 'Society', email as 'Account' FROM users WHERE role='manager'", conn)
        st.dataframe(all_socs, use_container_width=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            with st.form("add_soc"):
                st.subheader("➕ Register New Society"); n, e, p = st.text_input("Name"), st.text_input("Email"), st.text_input("Password")
                if st.form_submit_button("Create Account"):
                    if not n or not e or not p:
                        st.error("Name, email, and password are all required.")
                    else:
                        try:
                            conn.execute("INSERT OR REPLACE INTO users (email,password,society_name,role) VALUES (?,?,?,?)", (e, make_hash(p), n, 'manager'))
                            conn.commit(); st.rerun()
                        except Exception as ex:
                            st.error(f"Could not create account: {ex}")
        with col2:
            with st.form("reset_pw"):
                st.subheader("🔁 Reset Society Password")
                rp_target = st.selectbox("Select Account", ["Select..."] + all_socs['Account'].tolist(), key="rp_target")
                rp_new = st.text_input("New Password", type="password", key="rp_new")
                rp_confirm = st.text_input("Confirm Password", type="password", key="rp_confirm")
                if st.form_submit_button("Reset Password"):
                    if rp_target == "Select...":
                        st.error("Choose an account first.")
                    elif not rp_new:
                        st.error("Password cannot be empty.")
                    elif rp_new != rp_confirm:
                        st.error("Passwords don't match.")
                    else:
                        conn.execute("UPDATE users SET password=? WHERE email=?", (make_hash(rp_new), rp_target)); conn.commit()
                        st.success(f"Password reset for {rp_target}"); st.rerun()
        with col3:
            with st.form("del_soc"):
                st.subheader("🗑️ Delete Society"); target = st.selectbox("Select Account", ["Select..."] + all_socs['Account'].tolist())
                if st.form_submit_button("Remove Permanently"):
                    if target != "Select...": conn.execute("DELETE FROM users WHERE email=?", (target,)); conn.execute("DELETE FROM rosters WHERE society_email=?", (target,)); conn.commit(); st.rerun()
        conn.close()

        with st.expander("🔐 Change My Own Admin Password"):
            with st.form("self_pw"):
                cur_pw = st.text_input("Current Password", type="password", key="cur_pw")
                new_pw = st.text_input("New Password", type="password", key="new_pw")
                confirm_pw = st.text_input("Confirm New Password", type="password", key="confirm_pw")
                if st.form_submit_button("Update My Password"):
                    conn = get_db(); me_row = pd.read_sql(f"SELECT password FROM users WHERE email='{u_email}'", conn).iloc[0]
                    if me_row['password'] != make_hash(cur_pw):
                        st.error("Current password is incorrect."); conn.close()
                    elif not new_pw:
                        st.error("New password cannot be empty."); conn.close()
                    elif new_pw != confirm_pw:
                        st.error("New passwords don't match."); conn.close()
                    else:
                        conn.execute("UPDATE users SET password=? WHERE email=?", (make_hash(new_pw), u_email)); conn.commit(); conn.close()
                        st.success("Password updated successfully!")

    # --- IF MANAGER ---
    else:
        page = st.sidebar.radio("Navigate", ["🚀 Attendance Dashboard", "💰 Payroll Hub", "👥 Employee Configuration", "📅 Holiday Planner"])

        if page == "📅 Holiday Planner":
            st.header("Society Holiday Planner")
            conn = get_db(); u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{u_email}'", conn).iloc[0]; conn.close(); saved = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
            y = st.selectbox("Year", [2024,2025,2026]); m_name = st.selectbox("Month", list(calendar.month_name)[1:], index=datetime.now().month-1)
            calendar.setfirstweekday(calendar.SUNDAY); cal_matrix = calendar.monthcalendar(y, list(calendar.month_name).index(m_name)); weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            new_selections = []
            for week in cal_matrix:
                cols = st.columns(7)
                for i, day in enumerate(week):
                    if day != 0:
                        d_str = f"{y}-{list(calendar.month_name).index(m_name)+1:02d}-{day:02d}"
                        if cols[i].checkbox(f"{day} ({weekdays[i]})", value=d_str in saved, key=f"hp_{d_str}"): new_selections.append(d_str)
            if st.button("💾 Save Holiday Calendar"):
                other = [h for h in saved if not h.startswith(f"{y}-{list(calendar.month_name).index(m_name)+1:02d}")]; conn = get_db(); conn.execute('UPDATE users SET holidays=? WHERE email=?', (",".join(list(set(other + new_selections))), u_email)); conn.commit(); conn.close(); st.success("Updated!")

        elif page == "👥 Employee Configuration":
            st.header("Individual Roster & Financial Setup")
            conn = get_db(); roster_df = pd.read_sql(f"SELECT employee_name as 'Name', category as 'Department', pay_type as 'Salary Type', base_salary as 'Base Pay', ot_rate as 'OT Rate', late_penalty as 'Late Fee', absent_penalty as 'Absent Fee', half_day_rule as 'Half-Day Rule', shift_start as 'Start Time', shift_hours as 'Shift Hours', week_off as 'Mandatory Week Off' FROM rosters WHERE society_email='{u_email}'", conn); conn.close()
            if not roster_df.empty:
                edited = st.data_editor(roster_df, use_container_width=True, key="config_ed", column_config={"Salary Type": st.column_config.SelectboxColumn(options=["Monthly", "Daily"]), "Mandatory Week Off": st.column_config.SelectboxColumn(options=["None", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])}, disabled=["Department"])
                if st.button("💾 Save Changes"):
                    conn = get_db()
                    for _, r in edited.iterrows(): conn.execute('''UPDATE rosters SET week_off=?, shift_hours=?, base_salary=?, pay_type=?, shift_start=?, ot_rate=?, late_penalty=?, absent_penalty=?, half_day_rule=? WHERE employee_name=? AND society_email=?''', (r['Mandatory Week Off'], r['Shift Hours'], r['Base Pay'], r['Salary Type'], r['Start Time'], r['OT Rate'], r['Late Fee'], r['Absent Fee'], r['Half-Day Rule'], r['Name'], u_email))
                    conn.commit(); conn.close(); st.success("Updated!"); st.rerun()
            else: st.warning("Upload data first.")

        elif page == "💰 Payroll Hub":
            st.header("💰 Society Payroll Hub")
            if 'processed_data' not in st.session_state: st.warning("Process data in Dashboard first.")
            else:
                data = st.session_state.processed_data; sel_m = st.selectbox("Month", data['Month'].unique()); m_data = data[data['Month'] == sel_m]
                conn = get_db(); rost = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{u_email}'", conn).set_index('employee_name'); conn.close()
                pay_rows = []
                for n in m_data['Name'].unique():
                    if n not in rost.index: continue
                    e_df = m_data[m_data['Name'] == n]; r = rost.loc[n]
                    p, h, w, hl, l, ab = len(e_df[e_df['Status'] == 'Present']), len(e_df[e_df['Status'] == 'Half Day']), len(e_df[e_df['Status'] == 'Weekly Off']), len(e_df[e_df['Status'] == 'Holiday']), len(e_df[e_df['Punctuality'] == 'Late']), len(e_df[e_df['Status'] == 'Absent'])
                    ot_hrs = round(e_df['OT_Hrs'].sum(), 2); ot_p = round(ot_hrs * r['ot_rate'], 2)
                    late_fee = round(l * r['late_penalty'], 2); absent_fee = round(ab * r['absent_penalty'], 2); pens = late_fee + absent_fee
                    if r['pay_type'] == "Monthly": base = round((r['base_salary'] / 30) * (p + w + hl + (h * r['half_day_rule'])), 2)
                    else: base = round(r['base_salary'] * (p + (h * r['half_day_rule'])), 2)
                    pay_rows.append({
                        "Employee Name": n, "Salary Type": r['pay_type'],
                        "Present": p, "Absent": ab, "Half Day": h, "Holiday": hl, "Weekly Off": w, "Late Days": l,
                        "OT Hours": ot_hrs, "Base Earned": base, "OT Pay": ot_p, "Bonus": round(r['bonus'], 2),
                        "Late Fee Total": late_fee, "Absent Fee Total": absent_fee, "Total Fees": pens,
                        "Final Net Payable": round(base + ot_p + r['bonus'] - pens, 2)
                    })
                pay_df = pd.DataFrame(pay_rows); st.dataframe(pay_df, use_container_width=True)
                col1, col2 = st.columns(2); col1.download_button("📥 Master Excel", generate_master_excel(m_data, pay_df, sel_m), f"Payroll_{sel_m}.xlsx")
                worker = st.selectbox("Worker Slip (PDF)", pay_df['Employee Name'].unique())
                worker_pay = pay_df[pay_df['Employee Name'] == worker].iloc[0]
                worker_info = rost.loc[worker]
                st.download_button(
                    f"📄 Download PDF for {worker}",
                    generate_slip_pdf(u_name, sel_m, worker, worker_info, worker_pay, m_data[m_data['Name'] == worker]),
                    f"Slip_{worker}.pdf", "application/pdf"
                )

        elif page == "🚀 Attendance Dashboard":
            st.header("Attendance Dashboard")
            st.subheader("📂 Step 1: Upload Attendance CSV Dump")
            f = st.file_uploader("uploader", type="csv", label_visibility="collapsed")
            if f:
                df_raw = pd.read_csv(f); df_raw.columns = [str(c).strip().title() for c in df_raw.columns]
                conn = get_db()
                for _, row in df_raw[['Name', 'Type']].drop_duplicates().iterrows():
                    if not conn.execute('SELECT 1 FROM rosters WHERE employee_name=? AND society_email=?', (row['Name'], u_email)).fetchone():
                        conn.execute('INSERT INTO rosters (society_email, employee_name, category) VALUES (?,?,?)', (u_email, row['Name'], row['Type']))
                conn.commit(); conn.close()
                if st.button("🚀 Step 2: Process Attendance Data"):
                    conn = get_db(); rost_dict = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{u_email}'", conn).set_index('employee_name').to_dict('index'); u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{u_email}'", conn).iloc[0]; conn.close(); hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
                    date_cols = [col.split(' ')[0] for col in df_raw.columns if 'Duration' in col]
                    rows = []
                    for _, row in df_raw.iterrows():
                        name = row['Name']; emp = rost_dict.get(name, {'shift_hours': 8.0, 'week_off': 'Sunday', 'shift_start': '09:00 AM'})
                        for d in date_cols:
                            h_val = time_to_decimal(row.get(f"{d} Duration", 0)); in_t = str(row.get(f"{d} Check In", "00:00")); out_t = str(row.get(f"{d} Check Out", "00:00"))
                            dt = pd.to_datetime(d); is_off = (dt.strftime('%A').strip().lower() == str(emp['week_off']).strip().lower())
                            if is_off: s = "Weekly Off"
                            elif d in hols: s = "Holiday"
                            elif h_val >= emp['shift_hours']: s = "Present"
                            elif h_val >= (emp['shift_hours']/2): s = "Half Day"
                            else: s = "Absent"
                            try: act = datetime.strptime(in_t, "%I:%M %p") if " " in in_t else datetime.strptime(in_t, "%H:%M"); tgt = datetime.strptime(emp.get('shift_start','09:00 AM'), "%I:%M %p"); punc = "Late" if act > (tgt + timedelta(minutes=15)) else "On-Time"
                            except: punc = "On-Time"
                            rows.append({"Month": dt.strftime('%B %Y'), "Name": name, "Category": emp.get('category','General'), "Date": d, "Worked_Hrs": h_val, "OT_Hrs": max(0, h_val - emp.get('shift_hours',8.0)), "Status": s, "In": in_t, "Out": out_t, "Punctuality": punc})
                    st.session_state.processed_data = pd.DataFrame(rows)

            if 'processed_data' in st.session_state:
                data = st.session_state.processed_data
                latest = data['Date'].max(); today_df = data[data['Date'] == latest]
                conn = get_db(); rost_cnts = pd.read_sql(f"SELECT category, COUNT(*) as total FROM rosters WHERE society_email='{u_email}' GROUP BY category", conn); conn.close()
                st.subheader("📡 Live Manpower Summary")
                m_cols = st.columns(max(len(rost_cnts), 1))
                for i, (_, r_cnt) in enumerate(rost_cnts.iterrows()):
                    pres = len(today_df[(today_df['Category'] == r_cnt['category']) & (today_df['Status'] == 'Present')])
                    m_cols[i].markdown(f"<div class='manpower-card'><div class='manpower-label'>{r_cnt['category']}</div><div class='manpower-value'>{pres} / {r_cnt['total']}</div></div>", unsafe_allow_html=True)

                col_m, col_c = st.columns(2); sel_m = col_m.selectbox("Month View", data['Month'].unique()); sel_cat = col_c.selectbox("Filter Summary", ["All"] + data['Category'].unique().tolist())
                m_data = data[data['Month'] == sel_m]
                if sel_cat != "All": m_data = m_data[m_data['Category'] == sel_cat]
                st.subheader("📊 Society Summary Table"); st.dataframe(m_data.groupby(['Name', 'Category', 'Status']).size().unstack(fill_value=0).reset_index(), use_container_width=True)

                st.divider(); sel_n = st.selectbox("Individual Spotlight", m_data['Name'].unique()); p_df = m_data[m_data['Name'] == sel_n].sort_values('Date')
                html = ["<div class='nbh-cal-container'>"]
                for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]: html.append(f"<div class='nbh-cal-header'>{d}</div>")
                f_day = pd.to_datetime(p_df['Date'].min()); padding = (f_day.weekday() + 1) % 7
                for _ in range(padding): html.append("<div class='nbh-cal-day nbh-padding-day'></div>")
                mapping = {"Present": ("🟢", "Present", "#2E7D32"), "Absent": ("🔴", "Absent", "#D32F2F"), "Half Day": ("🌓", "Half Day", "#F9A825"), "Holiday": ("🏖️", "Holiday", "#1565C0"), "Weekly Off": ("ⓧ", "Weekly Off", "#999")}
                for _, r in p_df.iterrows():
                    is_off = "nbh-weekly-off" if r['Status'] == "Weekly Off" else ""; icon, label, color = mapping.get(r['Status'], ("❓", "??", "#000"))
                    t_info = f"<span class='nbh-time-text'>{format_pretty_time(r['Worked_Hrs'])}</span>" if r['Worked_Hrs'] > 0 else ""
                    body = f"<div class='nbh-off-label'>{icon} {label}</div>{t_info}" if r['Status'] == "Weekly Off" else f"<div class='nbh-status-box'><span class='nbh-status-icon'>{icon}</span><span class='nbh-status-label' style='color:{color};'>{label}</span>{t_info}</div>"
                    in_t, out_t = str(r["In"]).strip(), str(r["Out"]).strip()
                    has_real_time = in_t not in ("00:00", "0", "nan", "") and out_t not in ("00:00", "0", "nan", "")
                    footer = f"<div class='nbh-shift-footer'>{in_t} - {out_t}</div>" if has_real_time else ""
                    html.append(f'<div class="nbh-cal-day {is_off}"><span class="nbh-day-num">{pd.to_datetime(r["Date"]).day}</span>{body}{footer}</div>')
                st.markdown("".join(html) + "</div>", unsafe_allow_html=True)
