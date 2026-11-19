"""
AiEdit Logs Viewer - Streamlit page to monitor application logs and sessions
"""

import streamlit as st
from pathlib import Path
import json
from datetime import datetime
from logging_config import (
    get_recent_logs, get_error_logs, get_session_history,
    LOG_DIR, MAIN_LOG_FILE, ERROR_LOG_FILE, SESSION_LOG_FILE, clear_old_logs
)

st.set_page_config(
    page_title="AiEdit - Logs Viewer",
    page_icon="📊",
    layout="wide"
)

st.markdown("# 📊 AiEdit Logs & Monitoring")

# Sidebar options
st.sidebar.markdown("### Log Management")

view_option = st.sidebar.radio(
    "Select View:",
    options=["Overview", "Main Logs", "Error Logs", "Session History", "Log Files"]
)

if st.sidebar.button("🗑️ Clear Old Logs (>7 days)", use_container_width=True):
    with st.spinner("Clearing old logs..."):
        clear_old_logs(days=7)
    st.success("✓ Old logs cleared")

# ==================== Overview ====================
if view_option == "Overview":
    col1, col2, col3 = st.columns(3)
    
    with col1:
        sessions = get_session_history()
        st.metric("Total Sessions", len(sessions))
    
    with col2:
        completed = len([s for s in sessions if s.get("status") == "completed"])
        st.metric("Completed", completed)
    
    with col3:
        failed = len([s for s in sessions if s.get("status") == "failed"])
        st.metric("Failed", failed)
    
    st.markdown("---")
    
    st.markdown("### Recent Activity")
    
    if sessions:
        # Show last 5 sessions
        st.dataframe(
            [{
                "Time": s.get("timestamp", "N/A"),
                "Command": s.get("command", "N/A"),
                "Status": s.get("status", "N/A"),
                "Video": Path(s.get("video", "")).name
            } for s in sessions[-5:]],
            use_container_width=True
        )
    else:
        st.info("No sessions recorded yet")
    
    st.markdown("---")
    
    st.markdown("### System Info")
    st.info(f"""
    **Log Directory:** {LOG_DIR}
    
    **Main Log:** {MAIN_LOG_FILE.name}
    
    **Error Log:** {ERROR_LOG_FILE.name}
    
    **Sessions Log:** {SESSION_LOG_FILE.name}
    """)

# ==================== Main Logs ====================
elif view_option == "Main Logs":
    st.markdown("## Main Application Logs")
    
    num_lines = st.slider("Number of lines to display:", 10, 500, 100)
    
    logs = get_recent_logs(num_lines)
    
    st.code(logs, language="log")
    
    # Download button
    if logs != "No logs available yet":
        st.download_button(
            label="📥 Download Full Log",
            data=logs,
            file_name=f"aiedit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain"
        )

# ==================== Error Logs ====================
elif view_option == "Error Logs":
    st.markdown("## Error Logs")
    
    num_lines = st.slider("Number of lines to display:", 10, 200, 50)
    
    errors = get_error_logs(num_lines)
    
    if "No errors logged yet" in errors:
        st.success("✓ No errors recorded")
    else:
        st.code(errors, language="log")
        
        # Download button
        st.download_button(
            label="📥 Download Error Log",
            data=errors,
            file_name=f"aiedit_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain"
        )

# ==================== Session History ====================
elif view_option == "Session History":
    st.markdown("## Processing Session History")
    
    sessions = get_session_history()
    
    if not sessions:
        st.info("No sessions recorded yet")
    else:
        # Summary stats
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Sessions", len(sessions))
        with col2:
            completed = len([s for s in sessions if s.get("status") == "completed"])
            st.metric("Completed", completed)
        with col3:
            failed = len([s for s in sessions if s.get("status") == "failed"])
            st.metric("Failed", failed)
        with col4:
            started = len([s for s in sessions if s.get("status") == "started"])
            st.metric("In Progress", started)
        
        st.markdown("---")
        
        # Detailed table
        st.markdown("### All Sessions")
        
        session_data = []
        for session in reversed(sessions):  # Most recent first
            session_data.append({
                "Timestamp": session.get("timestamp", "N/A"),
                "Video": Path(session.get("video", "Unknown")).name,
                "Command": session.get("command", "N/A"),
                "Status": session.get("status", "N/A"),
                "Details": str(session.get("details", {}))
            })
        
        st.dataframe(session_data, use_container_width=True)
        
        # Download session history
        st.download_button(
            label="📥 Download Session History (JSON)",
            data=json.dumps(sessions, indent=2),
            file_name=f"aiedit_sessions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )

# ==================== Log Files ====================
elif view_option == "Log Files":
    st.markdown("## Available Log Files")
    
    log_files = list(LOG_DIR.glob("*.log")) + list(LOG_DIR.glob("*.json"))
    
    if not log_files:
        st.info("No log files found")
    else:
        col_name, col_size, col_modified, col_download = st.columns([2, 1, 1.5, 0.5])
        
        with col_name:
            st.write("**File Name**")
        with col_size:
            st.write("**Size**")
        with col_modified:
            st.write("**Modified**")
        with col_download:
            st.write("**Download**")
        
        st.markdown("---")
        
        for log_file in sorted(log_files, reverse=True):
            size_mb = log_file.stat().st_size / (1024 * 1024)
            modified = datetime.fromtimestamp(log_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            
            col1, col2, col3, col4 = st.columns([2, 1, 1.5, 0.5])
            
            with col1:
                st.write(f"`{log_file.name}`")
            with col2:
                st.write(f"{size_mb:.2f} MB")
            with col3:
                st.write(modified)
            with col4:
                with open(log_file, 'rb') as f:
                    st.download_button(
                        label="⬇️",
                        data=f.read(),
                        file_name=log_file.name,
                        key=str(log_file)
                    )

st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 20px; color: #888;">
    <p>🔍 <b>AiEdit Logs Viewer</b></p>
    <p><small>Monitor and debug your video processing tasks</small></p>
</div>
""", unsafe_allow_html=True)
