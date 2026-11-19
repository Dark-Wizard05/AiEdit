"""Streamlit-safe updates for the main prompt text area."""

from __future__ import annotations

import streamlit as st

PENDING_COMMAND_KEY = "pending_command_input"


def apply_pending_command() -> None:
    """Apply a queued prompt before ``command_input`` widget is instantiated."""

    pending = st.session_state.get(PENDING_COMMAND_KEY)
    if pending is not None:
        st.session_state.command_input = str(pending)
        st.session_state[PENDING_COMMAND_KEY] = None


def queue_command_prompt(text: str) -> None:
    """Queue prompt text for the next rerun (safe from any tab)."""

    st.session_state[PENDING_COMMAND_KEY] = text
    st.rerun()
