"""
Home Page
홈/게임 선택 페이지
"""

import streamlit as st

st.set_page_config(
    page_title="Home - Game Hub",
    page_icon="🏠",
    layout="wide"
)

st.title("🏠 홈")
st.write("게임을 선택하세요!")

# 메인 앱으로 리다이렉트
st.switch_page("app.py")
