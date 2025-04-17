import streamlit as st
import pandas as pd
from datetime import datetime
from jira import JIRA
from jinja2 import Environment, FileSystemLoader
import re
import os
import requests

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="JIRA Timesheet Viewer", layout="wide")
st.title("📅 JIRA Timesheet Viewer")

# -------------------- Load from Streamlit Secrets --------------------
JIRA_URL = st.secrets.get("JIRA_URL")
JIRA_API_TOKEN = st.secrets.get("JIRA_API_TOKEN")

if not JIRA_URL:
    st.error("❌ JIRA_URL is missing in Streamlit secrets.")
    st.stop()

if not JIRA_API_TOKEN:
    st.error("❌ JIRA_API_TOKEN is missing in Streamlit secrets.")
    st.stop()

# -------------------- JIRA Auth --------------------
try:
    jira = JIRA(server=JIRA_URL, token_auth=JIRA_API_TOKEN)
except Exception as e:
    st.error("Cannot reach JIRA server.")
    st.text(str(e))
    st.stop()

# -------------------- Helper Function --------------------
def parse_time_spent(time_str):
    if not time_str:
        return 0
    total_hours = 0.0
    if m := re.search(r'(\d+)\s*w', time_str):
        total_hours += int(m.group(1)) * 5 * 8
    if m := re.search(r'(\d+)\s*d', time_str):
        total_hours += int(m.group(1)) * 8
    if m := re.search(r'(\d+)\s*h', time_str):
        total_hours += int(m.group(1))
    if m := re.search(r'(\d+)\s*m', time_str):
        total_hours += int(m.group(1)) / 60.0
    return total_hours

# -------------------- Navigation --------------------
page = st.sidebar.selectbox("Select Page", ["Home", "Timesheet Viewer"])

# -------------------- Home Page --------------------
if page == "Home":
    st.write("Welcome to the JIRA Timesheet Viewer app")

# -------------------- Timesheet Viewer Page --------------------
if page == "Timesheet Viewer":
    # -------------------- Project Selection --------------------
    projects = jira.projects()
    project_dict = {f"{p.name} ({p.key})": p.key for p in projects}
    selected_display = st.selectbox("Choose from available projects", sorted(project_dict.keys()))
    selected_project = project_dict[selected_display]

    # Date Input for the timesheet viewer
    col1, col2 = st.columns(2)
    with col1:
        from_date = st.date_input("From Date", datetime(2025, 3, 24))
    with col2:
        to_date = st.date_input("To Date", datetime(2025, 3, 30))

    if from_date > to_date:
        st.error("❌ From Date must be earlier than To Date")
        st.stop()
    if (to_date - from_date).days > 30:
        st.error("❌ Maximum date range allowed is 30 days.")
        st.stop()

    # -------------------- JIRA Query --------------------
    jql = (
        f'project = "{selected_project}" '
        f'AND worklogDate >= "{from_date}" AND worklogDate <= "{to_date}" '
        f'ORDER BY updated DESC'
    )

    start_at, batch_size, issues = 0, 100, []
    while True:
        batch = jira.search_issues(jql, startAt=start_at, maxResults=batch_size)
        if not batch:
            break
        issues.extend(batch)
        start_at += len(batch)
        if len(batch) < batch_size:
            break

    # -------------------- Collect Worklog Data --------------------
    log_data = []
    for issue in issues:
        try:
            worklogs = jira.worklogs(issue.key)
            for log in worklogs:
                log_date = datetime.strptime(log.started[:10], "%Y-%m-%d").date()
                if from_date <= log_date <= to_date:
                    log_data.append({
                        "User": log.author.displayName,
                        "Date": log_date,
                        "IssueKey": issue.key,
                        "Summary": issue.fields.summary,
                        "TimeSpent": log.timeSpent
                    })
        except:
            continue

    # -------------------- Data Processing --------------------
    df = pd.DataFrame(log_data)
    if df.empty:
        st.warning("No logs found.")
        st.stop()

    df["Date"] = pd.to_datetime(df["Date"])
    users = sorted(df["User"].unique())
    all_dates = pd.date_range(from_date, to_date)
    formatted_dates = [(d.strftime("%Y-%m-%d"), d.strftime("%a"), d.weekday() >= 5) for d in all_dates]

    data = {}
    user_totals = {}
    grand_total = 0

    for user in users:
        user_total = 0
        data[user] = {}
        for d in all_dates:
            date_str = d.strftime("%Y-%m-%d")
            user_logs = df[(df["User"] == user) & (df["Date"].dt.date == d.date())]
            if not user_logs.empty:
                total, details = 0, []
                for _, row in user_logs.iterrows():
                    hours = parse_time_spent(row["TimeSpent"])
                    total += hours
                    details.append(f"[{row['IssueKey']}] {row['Summary']} — {row['TimeSpent']} ({round(hours, 2)}h)")
                data[user][date_str] = {"hours": round(total, 2), "details": details}
                user_total += total
                grand_total += total
            else:
                data[user][date_str] = None
        user_totals[user] = round(user_total, 2)

    # -------------------- Render HTML --------------------
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    template = env.get_template("index.html")

    rendered_html = template.render(
        from_date=from_date.strftime("%Y-%m-%d"),
        to_date=to_date.strftime("%Y-%m-%d"),
        users=users,
        dates=formatted_dates,
        data=data,
        user_totals=user_totals,
        grand_total=round(grand_total, 2)
    )

    st.components.v1.html(rendered_html, height=1200, scrolling=True)
