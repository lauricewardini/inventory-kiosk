import psycopg2
import streamlit as st

def get_conn():
    return psycopg2.connect(st.secrets["DATABASE_URL"])
