import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import hashlib
import base64
from io import BytesIO
import os
import uuid

# Set page configuration
st.set_page_config(
    page_title="Employee Management System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Database connection function
def get_db_connection():
    return psycopg2.connect(
        host=st.secrets["db_host"],
        database=st.secrets["db_name"],
        user=st.secrets["db_user"],
        password=st.secrets["db_password"],
        port=st.secrets["db_port"]
    )

# Initialize database tables if they don't exist
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Create users table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        password VARCHAR(100) NOT NULL,
        role VARCHAR(20) NOT NULL
    )
    ''')
    
    # Create work_reports table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS work_reports (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        report_date DATE NOT NULL,
        report_content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create tasks table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        task_description TEXT NOT NULL,
        due_date DATE,
        status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Insert admin user if not exists
    cur.execute("SELECT * FROM users WHERE username = 'admin'")
    if cur.fetchone() is None:
        # Create admin with password 'admin123'
        hashed_password = hashlib.sha256('admin123'.encode()).hexdigest()
        cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                   ('admin', hashed_password, 'admin'))
    
    conn.commit()
    cur.close()
    conn.close()

# Password hashing function
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Authentication function
def authenticate(username, password):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    hashed_password = hash_password(password)
    cur.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, hashed_password))
    user = cur.fetchone()
    
    cur.close()
    conn.close()
    
    return user

# Generate CSV download link
def get_csv_download_link(df, filename):
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="{filename}">Download CSV</a>'
    return href

# Admin Functions
def admin_create_employee():
    st.subheader("Create Employee Account")
    
    with st.form("create_employee_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Create Employee")
        
        if submit_button:
            if username and password:
                conn = get_db_connection()
                cur = conn.cursor()
                
                try:
                    hashed_password = hash_password(password)
                    cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                              (username, hashed_password, 'employee'))
                    conn.commit()
                    st.success(f"Employee {username} created successfully!")
                except psycopg2.errors.UniqueViolation:
                    st.error(f"Username {username} already exists!")
                finally:
                    cur.close()
                    conn.close()
            else:
                st.warning("Please fill all fields!")

def admin_manage_employees():
    st.subheader("Manage Employees")
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT id, username, role FROM users WHERE role = 'employee'")
    employees = cur.fetchall()
    
    if employees:
        employee_df = pd.DataFrame(employees)
        st.dataframe(employee_df)
        
        selected_employee = st.selectbox("Select Employee to Remove", 
                                         options=[e['username'] for e in employees],
                                         index=None)
        
        if selected_employee and st.button("Remove Employee"):
            employee_id = next(e['id'] for e in employees if e['username'] == selected_employee)
            
            # First delete related records
            cur.execute("DELETE FROM work_reports WHERE user_id = %s", (employee_id,))
            cur.execute("DELETE FROM tasks WHERE user_id = %s", (employee_id,))
            cur.execute("DELETE FROM users WHERE id = %s", (employee_id,))
            
            conn.commit()
            st.success(f"Employee {selected_employee} removed successfully!")
            st.rerun()
    else:
        st.info("No employees found.")
    
    cur.close()
    conn.close()

def admin_view_reports():
    st.subheader("View Employee Reports")
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get all employees
    cur.execute("SELECT id, username FROM users WHERE role = 'employee'")
    employees = cur.fetchall()
    
    if not employees:
        st.info("No employees found.")
        cur.close()
        conn.close()
        return
    
    # Filter options
    col1, col2, col3 = st.columns(3)
    
    with col1:
        selected_employee = st.selectbox(
            "Select Employee", 
            options=["All Employees"] + [e['username'] for e in employees]
        )
    
    with col2:
        report_period = st.selectbox(
            "Report Period",
            options=["Daily", "Weekly", "Monthly", "Yearly"]
        )
    
    with col3:
        today = datetime.now().date()
        if report_period == "Daily":
            selected_date = st.date_input("Select Date", value=today)
        elif report_period == "Weekly":
            week_start = today - timedelta(days=today.weekday())
            selected_date = st.date_input("Select Week Start", value=week_start)
        elif report_period == "Monthly":
            month_start = today.replace(day=1)
            selected_date = st.date_input("Select Month", value=month_start)
        else:  # Yearly
            year_start = today.replace(month=1, day=1)
            selected_date = st.date_input("Select Year", value=year_start)
    
    # Build query based on filters
    query = """
        SELECT u.username, wr.report_date, wr.report_content
        FROM work_reports wr
        JOIN users u ON wr.user_id = u.id
        WHERE 1=1
    """
    params = []
    
    if selected_employee != "All Employees":
        query += " AND u.username = %s"
        params.append(selected_employee)
    
    if report_period == "Daily":
        query += " AND wr.report_date = %s"
        params.append(selected_date)
    elif report_period == "Weekly":
        query += " AND wr.report_date BETWEEN %s AND %s"
        week_end = selected_date + timedelta(days=6)
        params.extend([selected_date, week_end])
    elif report_period == "Monthly":
        query += " AND EXTRACT(YEAR FROM wr.report_date) = %s AND EXTRACT(MONTH FROM wr.report_date) = %s"
        params.extend([selected_date.year, selected_date.month])
    else:  # Yearly
        query += " AND EXTRACT(YEAR FROM wr.report_date) = %s"
        params.append(selected_date.year)
    
    query += " ORDER BY wr.report_date DESC"
    
    cur.execute(query, params)
    reports = cur.fetchall()
    
    if reports:
        reports_df = pd.DataFrame(reports)
        st.dataframe(reports_df)
        
        # Download option
        st.markdown(get_csv_download_link(reports_df, f"reports_{report_period.lower()}.csv"), unsafe_allow_html=True)
    else:
        st.info("No reports found for the selected criteria.")
    
    cur.close()
    conn.close()

def admin_assign_task():
    st.subheader("Assign Tasks to Employees")
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get all employees
    cur.execute("SELECT id, username FROM users WHERE role = 'employee'")
    employees = cur.fetchall()
    
    if not employees:
        st.info("No employees found.")
        cur.close()
        conn.close()
        return
    
    with st.form("assign_task_form"):
        selected_employee = st.selectbox(
            "Select Employee", 
            options=[e['username'] for e in employees]
        )
        
        task_description = st.text_area("Task Description")
        due_date = st.date_input("Due Date", min_value=datetime.now().date())
        
        submit_button = st.form_submit_button("Assign Task")
        
        if submit_button:
            if selected_employee and task_description:
                employee_id = next(e['id'] for e in employees if e['username'] == selected_employee)
                
                cur.execute(
                    "INSERT INTO tasks (user_id, task_description, due_date) VALUES (%s, %s, %s)",
                    (employee_id, task_description, due_date)
                )
                
                conn.commit()
                st.success(f"Task assigned to {selected_employee} successfully!")
            else:
                st.warning("Please fill all fields!")
    
    # Show existing tasks
    st.subheader("Existing Tasks")
    
    cur.execute("""
        SELECT t.id, u.username, t.task_description, t.due_date, t.status
        FROM tasks t
        JOIN users u ON t.user_id = u.id
        ORDER BY t.due_date ASC
    """)
    
    tasks = cur.fetchall()
    
    if tasks:
        tasks_df = pd.DataFrame(tasks)
        st.dataframe(tasks_df)
    else:
        st.info("No tasks found.")
    
    cur.close()
    conn.close()

# Employee Functions
def employee_submit_report(user_id):
    st.subheader("Submit Daily Work Report")
    
    with st.form("submit_report_form"):
        report_date = st.date_input("Report Date", max_value=datetime.now().date())
        report_content = st.text_area("What did you accomplish today?")
        
        submit_button = st.form_submit_button("Submit Report")
        
        if submit_button:
            if report_content:
                conn = get_db_connection()
                cur = conn.cursor()
                
                # Check if report already exists for this date
                cur.execute(
                    "SELECT id FROM work_reports WHERE user_id = %s AND report_date = %s",
                    (user_id, report_date)
                )
                
                existing_report = cur.fetchone()
                
                if existing_report:
                    # Update existing report
                    cur.execute(
                        "UPDATE work_reports SET report_content = %s WHERE id = %s",
                        (report_content, existing_report[0])
                    )
                    success_message = "Report updated successfully!"
                else:
                    # Create new report
                    cur.execute(
                        "INSERT INTO work_reports (user_id, report_date, report_content) VALUES (%s, %s, %s)",
                        (user_id, report_date, report_content)
                    )
                    success_message = "Report submitted successfully!"
                
                conn.commit()
                cur.close()
                conn.close()
                
                st.success(success_message)
            else:
                st.warning("Please enter your work report!")

def employee_view_reports(user_id):
    st.subheader("View My Reports")
    
    # Filter options
    report_period = st.selectbox(
        "Report Period",
        options=["Daily", "Weekly", "Monthly", "Yearly"]
    )
    
    today = datetime.now().date()
    if report_period == "Daily":
        selected_date = st.date_input("Select Date", value=today)
    elif report_period == "Weekly":
        week_start = today - timedelta(days=today.weekday())
        selected_date = st.date_input("Select Week Start", value=week_start)
    elif report_period == "Monthly":
        month_start = today.replace(day=1)
        selected_date = st.date_input("Select Month", value=month_start)
    else:  # Yearly
        year_start = today.replace(month=1, day=1)
        selected_date = st.date_input("Select Year", value=year_start)
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Build query based on filters
    query = """
        SELECT report_date, report_content
        FROM work_reports
        WHERE user_id = %s
    """
    params = [user_id]
    
    if report_period == "Daily":
        query += " AND report_date = %s"
        params.append(selected_date)
    elif report_period == "Weekly":
        query += " AND report_date BETWEEN %s AND %s"
        week_end = selected_date + timedelta(days=6)
        params.extend([selected_date, week_end])
    elif report_period == "Monthly":
        query += " AND EXTRACT(YEAR FROM report_date) = %s AND EXTRACT(MONTH FROM report_date) = %s"
        params.extend([selected_date.year, selected_date.month])
    else:  # Yearly
        query += " AND EXTRACT(YEAR FROM report_date) = %s"
        params.append(selected_date.year)
    
    query += " ORDER BY report_date DESC"
    
    cur.execute(query, params)
    reports = cur.fetchall()
    
    if reports:
        reports_df = pd.DataFrame(reports)
        st.dataframe(reports_df)
        
        # Download option
        st.markdown(get_csv_download_link(reports_df, f"my_reports_{report_period.lower()}.csv"), unsafe_allow_html=True)
    else:
        st.info("No reports found for the selected criteria.")
    
    cur.close()
    conn.close()

def employee_view_tasks(user_id):
    st.subheader("My Tasks")
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT id, task_description, due_date, status, created_at
        FROM tasks
        WHERE user_id = %s
        ORDER BY 
            CASE WHEN status = 'pending' THEN 0 ELSE 1 END,
            due_date ASC
    """, (user_id,))
    
    tasks = cur.fetchall()
    
    if tasks:
        # Convert to dataframe for display
        tasks_df = pd.DataFrame(tasks)
        
        # Display tasks
        st.dataframe(tasks_df)
        
        # Allow marking tasks as complete
        st.subheader("Update Task Status")
        
        pending_tasks = [task for task in tasks if task['status'] == 'pending']
        
        if pending_tasks:
            task_options = {f"{t['id']}: {t['task_description'][:30]}...": t['id'] for t in pending_tasks}
            
            selected_task_display = st.selectbox("Select Task to Mark as Complete", 
                                             options=list(task_options.keys()),
                                             index=None)
            
            if selected_task_display and st.button("Mark as Complete"):
                selected_task_id = task_options[selected_task_display]
                
                cur.execute(
                    "UPDATE tasks SET status = 'completed' WHERE id = %s",
                    (selected_task_id,)
                )
                
                conn.commit()
                st.success("Task marked as complete!")
                st.rerun()
        else:
            st.info("No pending tasks found.")
    else:
        st.info("No tasks assigned to you.")
    
    cur.close()
    conn.close()

# Main Application
def main():
    # Initialize database
    init_db()
    
    # Session state for login
    if 'user' not in st.session_state:
        st.session_state.user = None
    
    # Application title
    st.title("Employee Management System")
    
    # Login/logout sidebar
    with st.sidebar:
        st.header("Navigation")
        
        if st.session_state.user:
            st.write(f"Logged in as: **{st.session_state.user['username']}**")
            
            if st.button("Logout"):
                st.session_state.user = None
                st.rerun()
        else:
            with st.form("login_form"):
                st.subheader("Login")
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                login_button = st.form_submit_button("Login")
                
                if login_button:
                    user = authenticate(username, password)
                    if user:
                        st.session_state.user = user
                        st.rerun()
                    else:
                        st.error("Invalid username or password")
    
    # Main content based on authentication
    if st.session_state.user:
        user = st.session_state.user
        
        if user['role'] == 'admin':
            # Admin Dashboard
            st.header("Admin Dashboard")
            
            tab1, tab2, tab3, tab4 = st.tabs([
                "Create Employee", 
                "Manage Employees", 
                "View Reports",
                "Assign Tasks"
            ])
            
            with tab1:
                admin_create_employee()
            
            with tab2:
                admin_manage_employees()
            
            with tab3:
                admin_view_reports()
            
            with tab4:
                admin_assign_task()
                
        else:
            # Employee Dashboard
            st.header("Employee Dashboard")
            
            tab1, tab2, tab3 = st.tabs([
                "Submit Report", 
                "View My Reports", 
                "My Tasks"
            ])
            
            with tab1:
                employee_submit_report(user['id'])
            
            with tab2:
                employee_view_reports(user['id'])
            
            with tab3:
                employee_view_tasks(user['id'])
    else:
        # Landing page
        st.info("Please login to access the system.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Admin Features")
            st.markdown("""
            - Create & manage employee accounts
            - View employee work reports
            - Filter reports by day, week, month, or year
            - Download employee reports
            - Assign tasks to employees
            """)
        
        with col2:
            st.subheader("Employee Features")
            st.markdown("""
            - Submit daily work reports
            - View personal work history
            - View assigned tasks
            - Mark tasks as complete
            """)

if __name__ == "__main__":
    main()
