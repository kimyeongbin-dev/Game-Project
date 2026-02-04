"""
Game Project - Streamlit Main App
게임 허브 메인 페이지
"""

import streamlit as st

st.set_page_config(
    page_title="Game Hub",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🎮 Game Hub")
st.write("다양한 보드게임을 즐겨보세요!")

st.markdown("---")

# 게임 목록
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    ### 🎯 쿼리도 (Quoridor)

    벽을 세워 상대를 막는 전략 보드게임

    - 2인 플레이 (vs AI)
    - 9x9 보드
    - 각 10개의 벽
    """)

    if st.button("🎮 쿼리도 플레이", use_container_width=True, type="primary"):
        st.switch_page("pages/2_Quoridor.py")

with col2:
    st.markdown("""
    ### 🔮 오목 (Gomoku)

    *준비 중...*

    5개의 돌을 연속으로 놓으면 승리
    """)

    st.button("🎮 오목 플레이", use_container_width=True, disabled=True)

with col3:
    st.markdown("""
    ### 🎲 더 많은 게임

    *준비 중...*

    새로운 게임이 곧 추가됩니다!
    """)

    st.button("🔜 Coming Soon", use_container_width=True, disabled=True)

st.markdown("---")

# 사이드바
with st.sidebar:
    st.header("📋 정보")
    st.write("버전: 0.1.0")
    st.write("백엔드: FastAPI")

    st.markdown("---")

    st.header("🔗 링크")
    st.write("- [게임 규칙](docs/quoridor/game_rules.md)")
    st.write("- [API 문서](http://localhost:8000/docs)")
