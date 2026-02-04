"""
Game Controls
게임 컨트롤 UI 컴포넌트
"""

import streamlit as st
from typing import Callable, Optional


def render_game_controls(
    game_state: dict,
    on_new_game: Callable,
    on_wall_mode_toggle: Callable,
    on_orientation_change: Callable,
    wall_mode: bool = False,
    wall_orientation: str = "horizontal"
):
    """
    게임 컨트롤 UI 렌더링

    Args:
        game_state: 게임 상태
        on_new_game: 새 게임 콜백
        on_wall_mode_toggle: 벽 모드 토글 콜백
        on_orientation_change: 벽 방향 변경 콜백
        wall_mode: 현재 벽 모드 여부
        wall_orientation: 현재 벽 방향
    """
    status = game_state["status"]
    current_turn = game_state["current_turn"]
    current_player = game_state["players"][f"player{current_turn}"]

    st.write("### 🎮 게임 컨트롤")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔄 새 게임", use_container_width=True):
            on_new_game()

    with col2:
        if status == "in_progress" and current_turn == 1:
            if current_player["walls_remaining"] > 0:
                mode_label = "🚶 이동 모드" if wall_mode else "🧱 벽 모드"
                if st.button(mode_label, use_container_width=True):
                    on_wall_mode_toggle()
            else:
                st.button("🧱 벽 없음", use_container_width=True, disabled=True)

    # 벽 모드일 때 방향 선택
    if wall_mode and status == "in_progress" and current_turn == 1:
        st.write("**벽 방향 선택:**")
        col1, col2 = st.columns(2)

        with col1:
            if st.button(
                "━━ 수평",
                use_container_width=True,
                type="primary" if wall_orientation == "horizontal" else "secondary"
            ):
                on_orientation_change("horizontal")

        with col2:
            if st.button(
                "┃┃ 수직",
                use_container_width=True,
                type="primary" if wall_orientation == "vertical" else "secondary"
            ):
                on_orientation_change("vertical")


def render_game_setup(
    on_start_game: Callable[[str, str], None],
    default_name: str = "Player"
):
    """
    게임 설정 UI 렌더링

    Args:
        on_start_game: 게임 시작 콜백 (player_name, difficulty)
        default_name: 기본 플레이어 이름
    """
    st.write("### 🎮 새 게임 시작")

    player_name = st.text_input(
        "플레이어 이름",
        value=default_name,
        max_chars=50
    )

    difficulty = st.select_slider(
        "AI 난이도",
        options=["easy", "normal", "hard"],
        value="normal",
        format_func=lambda x: {"easy": "쉬움 😊", "normal": "보통 🙂", "hard": "어려움 😤"}[x]
    )

    if st.button("🚀 게임 시작", use_container_width=True, type="primary"):
        on_start_game(player_name, difficulty)


def render_game_rules():
    """게임 규칙 표시"""
    with st.expander("📖 게임 규칙"):
        st.markdown("""
        ### 쿼리도(Quoridor) 규칙

        **목표**: 반대편 끝에 먼저 도달하면 승리!

        **당신 (🔵)**: 하단에서 시작 → 상단(row=0) 도달 시 승리
        **AI (🔴)**: 상단에서 시작 → 하단(row=8) 도달 시 승리

        **턴마다 선택:**
        1. **이동**: 상하좌우 1칸 이동 (⭕ 표시된 곳으로)
        2. **벽 설치**: 남은 벽(10개)로 상대 경로 방해

        **규칙:**
        - 벽은 2칸 길이
        - 상대방 경로를 완전히 막을 수 없음
        - 상대방 위에서 점프 가능
        """)


def render_turn_indicator(game_state: dict):
    """현재 턴 표시"""
    status = game_state["status"]
    current_turn = game_state["current_turn"]

    if status == "finished":
        winner = game_state.get("winner")
        winner_name = game_state["players"][f"player{winner}"]["name"]
        st.success(f"🎉 게임 종료! {winner_name} 승리!")
    elif current_turn == 1:
        st.info("🔵 당신의 턴입니다. 이동하거나 벽을 설치하세요.")
    else:
        st.warning("🔴 AI가 생각 중...")
