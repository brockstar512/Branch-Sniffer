"""Streamlit app — Phase 4 deliverable.

For Phase 1 this is a placeholder so the directory exists and the entry point
is known. Real UI built in Phase 4 of the 24-hour plan.

Run with:
    streamlit run app/streamlit_app.py
"""
import streamlit as st

st.set_page_config(page_title="Dog", page_icon="🐕")
st.title("🐕 Dog")
st.caption("Yo dog, drop your repo path and bug report — let's sniff this out.")
st.warning("Phase 4 UI not yet built. Use the CLI in the meantime: `python cli.py --help`")
