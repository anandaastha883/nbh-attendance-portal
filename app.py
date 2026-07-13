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
    .nbh-cal-container { display: grid; grid-template-columns: repeat(7, 1fr); width: 100%; border-top: 1px solid #e0e0e0; border-left: 1px solid #e0e0e0; background-color: white; margin-bottom: 20px; }
    .nbh-cal-header { text-align: center; padding: 12px; font-weight: 500; color: #888; border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0; background-color: #F8F9FA; text-transform: uppercase; font-size: 12px; }
    .nbh-cal-day { min-height: 140px; border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0; padding: 10px; position: relative; background-color: white; display: flex; flex-direction: column; align-items: center; }
    .nbh-padding-day { background-color: #fcfcfc; color: #ccc !important; }
    .nbh-weekly-off { background: repeating-linear-gradient(45deg, #ffffff, #ffffff 10px, #f5f5f5 10px, #f5f5f5 20px) !important; }
    .nbh-day-num { font-size: 14px; color: #666; font-weight: bold; align-self: flex-start; margin-bottom: 5px;}
    .nbh-status-label { font-size: 10px; font-weight: bold; text-transform: uppercase; margin-top: 5px; }
    .nbh-time-text { font-size: 11px; font-weight: 800; color: #333; }
    .nbh-shift-footer { position: absolute; bottom: 8px; font-size: 9px; color: #999; text-align: center; width: 100%; }
    .nbh-off-label { margin: auto; font-size: 10px; color: #bbb; font-weight: bold; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CORE HELPERS ---
def make_hash(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db(): return sqlite3.connect('societies.db', check_same_thread=False)
def format_pretty_time(decimal_hours):
    h, m = int(decimal_hours), int(round((decimal_hours - int(decimal_hours)) * 60))
    return f"{h}h {m}m"

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00"]: return 0.0
    try:
        if isinstance(t, (int, float)): return float(t)
        p = str(t).split(':')
        return int(p[0]) + (int(p[1])/60.0)
    except: return 0.0

# --- 3. REPORT GENERATORS ---
def generate_master_excel(full_data, pay_df, month):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pay_df.to_excel(writer, sheet_name='Payroll_Summary', index=False)
        full_data.to_excel(writer, sheet_name='Attendance_Logs', index=False)
        workbook = writer.book
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
        for sn in writer.sheets:
            ws = writer.sheets[sn]; ws.set_column('A:Z', 18)
    return output.getvalue()

def generate_slip_pdf(soc, month, name, p_df, net_val):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, f"{soc}", 0, 1, "C")
    pdf.set_font("Arial", "", 12); pdf.cell(190, 10, f"Salary Slip: {month}", 0, 1, "C"); pdf.ln(10)
    pdf.set_font("Arial", "B", 11); pdf.cell(190, 10, f"Employee: {name}", 0, 1)
    pdf.set_font("Arial", "B", 10); pdf.cell(190, 10, f"Net Payable: Rs. {net_val}", 1, 1); pdf.ln(5)
    pdf.set_font("Arial", "B", 8); cols = ["Date", "Status", "Hours"]; w = [40, 70, 40]
    for i, c in enumerate(cols): pdf.cell(w[i], 10, c, 1)
    pdf.ln(); pdf.set_font("Arial", "", 8)
    for _, r in p_df.iterrows():
        pdf.cell(w[0], 10, str(r['Date']), 1); pdf.cell(w[1], 10, str(r['Status']), 1); pdf.cell(w[2], 10, format_pretty_time(r['Worked_Hrs']), 1); pdf.ln()
    return bytes(pdf.output())

# --- 4. AUTH & CACHE GUARD ---
if 'auth' not in st.session_state: st.session_state.auth = {'logged_in': False}

if not st.session_state.auth['logged_in']:
    st.title("🏢 NoBrokerHood HRMS Login")
    with st.form("login"):
        e = st.text_input("Email"); p = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            conn = get_db(); user = pd.read_sql(f"SELECT * FROM users WHERE email='{e}'", conn); conn.close()
            if not user.empty and make_hash(p) == user.iloc[0]['password']:
                st.session_state.auth = {'logged_in': True, 'user': e, 'name': user.iloc[0]['society_name']}
                st.session_state.pop('processed_data', None) # Clear stale data
                st.rerun()
            else: st.error("❌ Invalid Login")
else:
    user_email, full_name = st.session_state.auth['user'], st.session_state.auth['name']
    st.sidebar.title(f"👋 {full_name}")
    page = st.sidebar.radio("Navigate", ["🚀 Dashboard", "💰 Payroll Hub", "👥 Employee Configuration", "📅 Holiday Calendar"])
    if st.sidebar.button("Logout"): st.session_state.auth = {'logged_in': False}; st.rerun()

    # --- PAGE: HOLIDAYS ---
    if page == "📅 Holiday Calendar":
        st.header("Public Holiday Planner")
        conn = get_db(); u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{user_email}'", conn).iloc[0]; conn.close()
        saved_hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
        cy, cm = st.columns(2); year = cy.selectbox("Year", [2024, 2025, 2026]); m_name = cm.selectbox("Month", list(calendar.month_name)[1:], index=datetime.now().month-1)
        m_num = list(calendar.month_name).index(m_name); calendar.setfirstweekday(calendar.SUNDAY); cal_matrix = calendar.monthcalendar(year, m_num); weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        new_selections = []
        for week in cal_matrix:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day != 0:
                    d_str = f"{year}-{m_num:02d}-{day:02d}"
                    if cols[i].checkbox(f"{day} ({weekdays[i]})", value=d_str in saved_hols, key=f"hp_{d_str}"): new_selections.append(d_str)
        if st.button("💾 Save Holidays"):
            other_hols = [h for h in saved_hols if not h.startswith(f"{year}-{m_num:02d}")]
            conn = get_db(); conn.execute('UPDATE users SET holidays=? WHERE email=?', (",".join(list(set(other_hols + new_selections))), user_email)); conn.commit(); conn.close(); st.success("Updated!")

    # --- PAGE: EMPLOYEE CONFIGURATION ---
    elif page == "👥 Employee Configuration":
        st.header("Personnel & Financial Settings")
        conn = get_db()
        cats_df = pd.read_sql(f"SELECT DISTINCT category FROM rosters WHERE society_email='{user_email}'", conn)
        cat_list = ["All Departments"] + [c for c in cats_df['category'].tolist() if c]
        sel_cat = st.selectbox("🎯 Filter by Department", cat_list)
        query = f"""SELECT employee_name as 'Employee Name', category as 'Department', pay_type as 'Salary Type', base_salary as 'Base Pay', ot_rate as 'OT Rate (per hr)', late_penalty as 'Late Fee', absent_penalty as 'Absent Fee', shift_start as 'Start Time', shift_hours as 'Total Shift Hours', week_off as 'Mandatory Week Off' FROM rosters WHERE society_email='{user_email}'"""
        if sel_cat != "All Departments": query += f" AND category='{sel_cat}'"
        roster_df = pd.read_sql(query, conn); conn.close()
        if not roster_df.empty:
            edited = st.data_editor(roster_df, use_container_width=True, key="config_ed", column_config={"Salary Type": st.column_config.SelectboxColumn(options=["Monthly", "Daily", "Hourly"]), "Mandatory Week Off": st.column_config.SelectboxColumn(options=["None", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])}, disabled=["Department"])
            if st.button("💾 Save All Changes"):
                conn = get_db()
                for _, r in edited.iterrows():
                    conn.execute('''UPDATE rosters SET shift_hours=?, week_off=?, shift_start=?, base_salary=?, pay_type=?, ot_rate=?, late_penalty=?, absent_penalty=? WHERE employee_name=? AND society_email=?''', (r['Total Shift Hours'], r['Mandatory Week Off'], r['Start Time'], r['Base Pay'], r['Salary Type'], r['OT Rate (per hr)'], r['Late Fee'], r['Absent Fee'], r['Employee Name'], user_email))
                conn.commit(); conn.close(); st.success("Updated!")
        else: st.warning("Upload data in Dashboard first.")

    # --- PAGE: PAYROLL HUB ---
    elif page == "💰 Payroll Hub":
        st.header("💰 Society Payroll Hub")
        if 'processed_data' not in st.session_state: st.warning("Process data in Dashboard first.")
        else:
            data = st.session_state.processed_data; sel_month = st.selectbox("Select Month", data['Month'].unique())
            m_data = data[data['Month'] == sel_month]
            conn = get_db(); rost_info = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{user_email}'", conn).set_index('employee_name'); conn.close()
            payroll_rows = []
            for n in m_data['Name'].unique():
                if n not in rost_info.index: continue
                e_df = m_data[m_data['Name'] == n]; r = rost_info.loc[n]
                p, h, w, hl, l, ab = len(e_df[e_df['Status'] == 'Present']), len(e_df[e_df['Status'] == 'Half Day']), len(e_df[e_df['Status'] == 'Weekly Off']), len(e_df[e_df['Status'] == 'Holiday']), len(e_df[e_df['Punctuality'] == 'Late']), len(e_df[e_df['Status'] == 'Absent'])
                ot_p = round(e_df['OT_Hrs'].sum() * r['ot_rate'], 2); pens = (l * r['late_penalty']) + (ab * r['absent_penalty'])
                if r['pay_type'] == "Monthly": base = round((r['base_salary'] / len(e_df)) * (p + w + hl + (h * r['half_day_rule'])), 2) if len(e_df) > 0 else 0
                else: base = round(r['base_salary'] * (p + (h * r['half_day_rule'])), 2)
                payroll_rows.append({"Employee Name": n, "Salary Type": r['pay_type'], "Base Earned": base, "OT Pay": ot_p, "Total Deductions": pens, "Final Net Payable": round(base + ot_p - pens, 2)})
            
            pay_df = pd.DataFrame(payroll_rows)
            st.dataframe(pay_df, use_container_width=True, hide_index=True)
            col1, col2 = st.columns(2)
            col1.download_button("📥 Master Excel Report", generate_master_excel(m_data, pay_df, sel_month), f"Master_Payroll_{sel_month}.xlsx")
            
            st.divider()
            sel_worker = st.selectbox("Select Worker for Individual PDF Slip", pay_df['Employee Name'].unique())
            indiv_pay = pay_df[pay_df['Employee Name'] == sel_worker]['Final Net Payable'].iloc[0]
            st.download_button(f"📄 Download PDF Slip for {sel_worker}", generate_slip_pdf(full_name, sel_month, sel_worker, m_data[m_data['Name']==sel_worker], indiv_pay), f"Slip_{sel_worker}.pdf", "application/pdf")

    # --- PAGE: DASHBOARD ---
    elif page == "🚀 Dashboard":
        st.header("Attendance Analysis Engine")
        f = st.file_uploader("Upload CSV", type="csv")
        if f:
            df_raw = pd.read_csv(f); df_raw.columns = [str(c).strip().title() for c in df_raw.columns]
            conn = get_db()
            for _, row in df_raw[['Name', 'Type']].drop_duplicates().iterrows():
                if not conn.execute('SELECT 1 FROM rosters WHERE employee_name=? AND society_email=?', (row['Name'], user_email)).fetchone():
                    conn.execute('INSERT INTO rosters (society_email, employee_name, category) VALUES (?,?,?)', (user_email, row['Name'], row['Type']))
            conn.commit(); conn.close()
            if st.button("🚀 Process Data"):
                conn = get_db(); rost = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{user_email}'", conn).set_index('employee_name').to_dict('index')
                u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{user_email}'", conn).iloc[0]; conn.close(); hols = [h.strip() for h in u_info['holidays'].split(",") if h.strip()]
                date_cols = [col.split(' ')[0] for col in df_raw.columns if 'Duration' in col]
                final_rows = []
                for _, row in df_raw.iterrows():
                    name = row['Name']; emp_r = rost.get(name, {'shift_hours': 8.0, 'week_off': 'Sunday', 'shift_start': '09:00 AM', 'category': 'General'})
                    for d in date_cols:
                        hrs = time_to_decimal(row.get(f"{d} Duration", 0)); in_t = str(row.get(f"{d} Check In", "00:00")); out_t = str(row.get(f"{d} Check Out", "00:00"))
                        is_late = "On-Time"
                        try:
                            act = datetime.strptime(in_t, "%I:%M %p") if " " in in_t else datetime.strptime(in_t, "%H:%M")
                            tgt = datetime.strptime(emp_r['shift_start'], "%I:%M %p")
                            if act > (tgt + timedelta(minutes=15)): is_late = "Late"
                        except: pass
                        dt = pd.to_datetime(d); s = "Absent"
                        if hrs >= emp_r['shift_hours']: s = "Present"
                        elif hrs >= (emp_r['shift_hours']/2): s = "Half Day"
                        elif d in hols: s = "Holiday"
                        elif dt.strftime('%A') == emp_r['week_off']: s = "Weekly Off"
                        final_rows.append({"Month": dt.strftime('%B %Y'), "Name": name, "Category": emp_r['category'], "Date": d, "Worked_Hrs": hrs, "OT_Hrs": max(0, hrs - emp_r['shift_hours']), "Status": s, "In": in_t, "Out": out_t, "Punctuality": is_late})
                st.session_state.processed_data = pd.DataFrame(final_rows)

        if 'processed_data' in st.session_state:
            data = st.session_state.processed_data; sel_month = st.selectbox("Month View", data['Month'].unique())
            m_data = data[data['Month'] == sel_month]; st.subheader("📊 Society Overview")
            st.dataframe(m_data.groupby(['Name', 'Category', 'Status']).size().unstack(fill_value=0).reset_index(), use_container_width=True)
            st.divider(); st.header("👤 Individual Spotlight")
            sel_name = st.selectbox("Select Employee", m_data['Name'].unique()); p_df = m_data[m_data['Name'] == sel_name].sort_values('Date')
            
            html = ["<div class='nbh-cal-container'>"]
            for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]: html.append(f"<div class='nbh-cal-header'>{d}</div>")
            f_day = pd.to_datetime(p_df['Date'].min()); padding = (f_day.weekday() + 1) % 7
            for _ in range(padding): html.append("<div class='nbh-cal-day nbh-padding-day'></div>")
            mapping = {"Present": ("🟢", "#2E7D32"), "Absent": ("🔴", "#D32F2F"), "Half Day": ("🌓", "#F9A825"), "Holiday": ("🏖️", "#1565C0"), "Weekly Off": ("ⓧ", "#999")}
            for _, r in p_df.iterrows():
                is_off = "nbh-weekly-off" if r['Status'] == "Weekly Off" else ""; icon, color = mapping.get(r['Status'], ("❓", "#000"))
                today_cls = "nbh-today-circle" if pd.to_datetime(r['Date']).day == datetime.now().day else ""
                body = f"<div class='nbh-off-label'>{icon} {r['Status']}</div>" if is_off else f"<div class='nbh-status-box'><span class='nbh-status-icon'>{icon}</span><span class='nbh-status-label' style='color:{color};'>{r['Status']}</span><span class='nbh-time-text'>{format_pretty_time(r['Worked_Hrs'])}</span></div>"
                html.append(f'<div class="nbh-cal-day {is_off}"><span class="nbh-day-num"><span class="{today_cls}">{pd.to_datetime(r["Date"]).day}</span></span>{body}<div class="nbh-shift-footer">{r["In"]} - {r["Out"]}</div></div>')
            html.append("</div>"); st.markdown("".join(html), unsafe_allow_html=True)
