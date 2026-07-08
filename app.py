import streamlit as st
import pandas as pd
import sqlite3
import io
import hashlib
from datetime import datetime

# --- 1. SETTINGS & HELPERS ---
st.set_page_config(page_title="NBH Workforce Pro V2", layout="wide")

def make_hash(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db(): return sqlite3.connect('societies.db', check_same_thread=False)

def format_hmm(decimal_hours):
    """Converts 3.5 decimal to 3.30 H.MM string"""
    hours = int(decimal_hours)
    minutes = int(round((decimal_hours - hours) * 60))
    return f"{hours}.{minutes:02d}"

def time_to_decimal(t):
    if pd.isna(t) or str(t).strip() in ["", "0", "00:00:00"]: return 0.0
    try:
        if isinstance(t, (int, float)): return float(t)
        p = str(t).split(':')
        if len(p) >= 2: return int(p[0]) + (int(p[1])/60.0)
        return float(t)
    except: return 0.0

# --- 2. AUTHENTICATION ---
if 'auth' not in st.session_state:
    st.session_state.auth = {'logged_in': False, 'user': None, 'name': None}

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

    st.title(f"🏢 {full_name} Management Console")
    
    # ADDED: Reset Button to clear memory if code changes
    if st.sidebar.button("🔄 Clear App Cache"):
        for key in list(st.session_state.keys()):
            if key != 'auth': del st.session_state[key]
        st.rerun()

    tab1, tab2, tab3 = st.tabs(["🚀 Dashboard & Analytics", "👥 Roster Manager", "📅 Society Holidays"])

    # --- TAB 3: HOLIDAY CALENDAR ---
    with tab3:
        st.header("Society Holiday Calendar")
        conn = get_db()
        u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{user_email}'", conn).iloc[0]
        conn.close()
        try: current_hols = [datetime.strptime(d.strip(), "%Y-%m-%d").date() for d in u_info['holidays'].split(",") if d.strip()]
        except: current_hols = []
        new_hols = st.date_input("Select Public Holidays", value=current_hols)
        if st.button("💾 Save Holiday Calendar"):
            h_list = [d.strftime("%Y-%m-%d") for d in new_hols] if isinstance(new_hols, (list, tuple)) else [new_hols.strftime("%Y-%m-%d")]
            conn = get_db(); conn.execute('UPDATE users SET holidays=? WHERE email=?', (",".join(h_list), user_email))
            conn.commit(); conn.close(); st.success("Holidays Updated!")

    # --- TAB 2: ROSTER MANAGER ---
    with tab2:
        st.header("Individual Roster Setup")
        conn = get_db()
        roster_df = pd.read_sql(f"SELECT employee_name as 'Name', category as 'Category', shift_hours as 'Shift_Hrs', week_off as 'Week_Off' FROM rosters WHERE society_email='{user_email}'", conn)
        conn.close()
        if not roster_df.empty:
            edited_roster = st.data_editor(roster_df, use_container_width=True, key="roster_editor_v2",
                column_config={"Week_Off": st.column_config.SelectboxColumn("Mandatory Week Off", options=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], required=True)},
                disabled=["Category"])
            if st.button("💾 Save Individual Rules"):
                conn = get_db()
                for _, r in edited_roster.iterrows():
                    conn.execute('UPDATE rosters SET shift_hours=?, week_off=? WHERE employee_name=? AND society_email=?', (r['Shift_Hrs'], r['Week_Off'], r['Name'], user_email))
                conn.commit(); conn.close(); st.success("Rules Saved!")
        else: st.warning("Upload data in Dashboard first.")

    # --- TAB 1: DASHBOARD ---
    with tab1:
        f = st.file_uploader("Upload Attendance Dump (CSV)", type="csv")
        if f:
            df_raw = pd.read_csv(f)
            df_raw.columns = [c.strip().title() for c in df_raw.columns]
            conn = get_db()
            for _, row in df_raw[['Name', 'Type']].drop_duplicates().iterrows():
                exists = conn.execute('SELECT 1 FROM rosters WHERE employee_name=? AND society_email=?', (row['Name'], user_email)).fetchone()
                if not exists:
                    conn.execute('INSERT INTO rosters (society_email, employee_name, category, shift_hours, week_off) VALUES (?,?,?,8.0,"Sunday")', (user_email, row['Name'], row['Type']))
            conn.commit(); conn.close()

            if st.button("🚀 Run Logic Engine"):
                conn = get_db()
                rost_dict = pd.read_sql(f"SELECT * FROM rosters WHERE society_email='{user_email}'", conn).set_index('employee_name').to_dict('index')
                u_info = pd.read_sql(f"SELECT holidays FROM users WHERE email='{user_email}'", conn).iloc[0]
                conn.close()
                h_list = [h.strip() for h in u_info['holidays'].split(",")] if u_info['holidays'] else []
                date_cols = [col.split(' ')[0] for col in df_raw.columns if 'Duration' in col]
                
                all_data = []
                for _, row in df_raw.iterrows():
                    name = row['Name']
                    emp_r = rost_dict.get(name, {'shift_hours': 8.0, 'week_off': 'Sunday', 'category': 'General'})
                    for d in date_cols:
                        hrs = time_to_decimal(row.get(f"{d} Duration", 0))
                        dt = pd.to_datetime(d)
                        ot_hrs = max(0, hrs - emp_r['shift_hours'])
                        
                        if hrs >= emp_r['shift_hours']: s = "Present"
                        elif hrs >= (emp_r['shift_hours']/2): s = "Half Day"
                        elif d in h_list: s = "Holiday"
                        elif dt.strftime('%A') == emp_r['week_off']: s = "Weekly Off"
                        else: s = "Absent"
                        
                        all_data.append({
                            "Month": dt.strftime('%B %Y'), "Name": name, "Date": d, 
                            "Hrs": hrs, "OT": ot_hrs, "Status": s, "Cat": emp_r['category']
                        })
                st.session_state.final_data = pd.DataFrame(all_data)

        if 'final_data' in st.session_state:
            data = st.session_state.final_data
            
            # SAFE CHECK: Make sure the required column exists
            if 'OT' not in data.columns:
                st.error("⚠️ Data format mismatch. Please click 'Clear App Cache' in the sidebar and rerun the engine.")
            else:
                available_months = data['Month'].unique().tolist()
                selected_month = st.selectbox("📅 Select Month for Analysis", available_months)
                m_data = data[data['Month'] == selected_month]

                # --- METRICS ---
                st.subheader(f"📈 {selected_month} Insights")
                m1, m2, m3 = st.columns(3)
                present_count = len(m_data[m_data['Status'] == 'Present'])
                m1.metric("Attendance %", f"{round((present_count/len(m_data))*100)}%")
                m2.metric("Total OT (H.MM)", format_hmm(m_data['OT'].sum()))
                m3.metric("Employees Tracked", m_data['Name'].nunique())

                # --- SUMMARY ---
                st.subheader(f"📊 {selected_month} Summary Table")
                summary = m_data.groupby(['Name', 'Cat', 'Status']).size().unstack(fill_value=0).reset_index()
                st.dataframe(summary, use_container_width=True)

                st.divider()
                st.subheader("👤 Individual Calendar Spotlight")
                sel_name = st.selectbox("Select Employee", m_data['Name'].unique())
                p_df = m_data[m_data['Name'] == sel_name].sort_values('Date').copy()
                p_df['dt'] = pd.to_datetime(p_df['Date'])
                
                grid = st.columns(7)
                for i, d_head in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]): 
                    grid[i].markdown(f"<center><b>{d_head}</b></center>", unsafe_allow_html=True)
                
                for _, r in p_df.iterrows():
                    target_col = r['dt'].weekday()
                    color = "#C8E6C9" if r['Status']=="Present" else "#FFF9C4" if r['Status']=="Half Day" else "#FFCDD2" if r['Status']=="Absent" else "#BBDEFB"
                    with grid[target_col]:
                        st.markdown(f"""
                            <div style='background-color:{color}; padding:5px; border-radius:5px; margin-bottom:5px; text-align:center; border:1px solid #ddd; min-height:60px;'>
                                <b>{r['dt'].day}</b><br><span style='font-size:10px;'>{format_hmm(r['Hrs'])}</span>
                            </div>
                        """, unsafe_allow_html=True)
                
                # --- EXPORT ---
                st.sidebar.markdown("---")
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                    summary.to_excel(writer, sheet_name=f'Summary', index=False)
                    m_data.to_excel(writer, sheet_name='Logs', index=False)
                st.sidebar.download_button(f"📥 Download {selected_month} Report", buf.getvalue(), f"Report_{selected_month.replace(' ','_')}.xlsx")

    # Logout
    if st.sidebar.button("Logout"):
        st.session_state.auth = {'logged_in': False}; st.rerun()
