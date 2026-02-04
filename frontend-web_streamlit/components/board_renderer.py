"""
Board Renderer
쿼리도 보드 렌더링 컴포넌트
"""

import streamlit as st
from typing import Optional, Callable


def render_board(
    game_state: dict,
    valid_moves: Optional[list] = None,
    on_cell_click: Optional[Callable] = None,
    on_wall_click: Optional[Callable] = None,
    wall_mode: bool = False,
    wall_orientation: str = "horizontal"
):
    """
    쿼리도 보드 렌더링

    Args:
        game_state: 게임 상태 딕셔너리
        valid_moves: 유효한 이동 위치 리스트
        on_cell_click: 셀 클릭 콜백
        on_wall_click: 벽 클릭 콜백
        wall_mode: 벽 설치 모드 여부
        wall_orientation: 벽 방향 ("horizontal" or "vertical")
    """
    valid_moves = valid_moves or []
    valid_positions = {(m["row"], m["col"]) for m in valid_moves}

    # 플레이어 위치
    p1_pos = game_state["players"]["player1"]["position"]
    p2_pos = game_state["players"]["player2"]["position"]
    p1_position = (p1_pos["row"], p1_pos["col"])
    p2_position = (p2_pos["row"], p2_pos["col"])

    # 벽 정보 파싱
    walls = game_state.get("walls", [])
    blocked_h = set()  # 수평 벽으로 차단된 셀 경계
    blocked_v = set()  # 수직 벽으로 차단된 셀 경계

    for wall in walls:
        r, c = wall["row"], wall["col"]
        if wall["orientation"] == "horizontal":
            blocked_h.add((r, c))
            blocked_h.add((r, c + 1))
        else:
            blocked_v.add((r, c))
            blocked_v.add((r + 1, c))

    # CSS 스타일
    st.markdown("""
    <style>
    .board-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0;
    }
    .board-row {
        display: flex;
        gap: 0;
    }
    .cell {
        width: 50px;
        height: 50px;
        border: 1px solid #ccc;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        cursor: pointer;
        background-color: #f5f5dc;
    }
    .cell:hover {
        background-color: #e0e0c0;
    }
    .cell.valid {
        background-color: #90EE90;
    }
    .cell.valid:hover {
        background-color: #7CCD7C;
    }
    .wall-h {
        border-bottom: 4px solid #8B4513 !important;
    }
    .wall-v {
        border-right: 4px solid #8B4513 !important;
    }
    .player1 {
        color: #0066cc;
    }
    .player2 {
        color: #cc0000;
    }
    </style>
    """, unsafe_allow_html=True)

    # 보드 렌더링 (Streamlit 버튼 기반)
    st.write("##### 🎮 게임 보드")

    cols_header = st.columns([0.5] + [1] * 9)
    cols_header[0].write("")
    for c in range(9):
        cols_header[c + 1].write(f"**{c}**")

    for row in range(9):
        cols = st.columns([0.5] + [1] * 9)
        cols[0].write(f"**{row}**")

        for col in range(9):
            cell_key = f"cell_{row}_{col}"
            position = (row, col)

            # 셀 내용 결정
            if position == p1_position:
                label = "🔵"  # Player 1
            elif position == p2_position:
                label = "🔴"  # Player 2
            elif position in valid_positions and not wall_mode:
                label = "⭕"  # 유효한 이동
            else:
                label = "·"

            # 버튼 스타일 결정
            is_valid = position in valid_positions
            button_type = "primary" if is_valid and not wall_mode else "secondary"

            with cols[col + 1]:
                if st.button(
                    label,
                    key=cell_key,
                    use_container_width=True,
                    type=button_type
                ):
                    if on_cell_click and not wall_mode:
                        on_cell_click(row, col)

    # 벽 모드일 때 벽 설치 그리드
    if wall_mode:
        st.write("##### 🧱 벽 설치 위치 선택")
        st.caption(f"현재 방향: {'━━ 수평' if wall_orientation == 'horizontal' else '┃┃ 수직'}")

        for row in range(8):
            cols = st.columns(8)
            for col in range(8):
                wall_key = f"wall_{row}_{col}"

                # 이미 설치된 벽 확인
                is_blocked = False
                for wall in walls:
                    if wall["row"] == row and wall["col"] == col:
                        is_blocked = True
                        break

                with cols[col]:
                    if is_blocked:
                        st.button("❌", key=wall_key, disabled=True)
                    else:
                        if st.button(
                            "🟫" if wall_orientation == "horizontal" else "🟫",
                            key=wall_key
                        ):
                            if on_wall_click:
                                on_wall_click(row, col, wall_orientation)


def render_game_info(game_state: dict):
    """게임 정보 렌더링"""
    status = game_state["status"]
    current_turn = game_state["current_turn"]
    turn_count = game_state["turn_count"]
    winner = game_state.get("winner")

    p1 = game_state["players"]["player1"]
    p2 = game_state["players"]["player2"]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            label=f"🔵 {p1['name']}",
            value=f"벽: {p1['walls_remaining']}",
            delta="현재 턴" if current_turn == 1 and status == "in_progress" else None
        )

    with col2:
        if status == "finished":
            if winner == 1:
                st.success(f"🎉 {p1['name']} 승리!")
            else:
                st.error(f"😔 {p2['name']} 승리!")
        else:
            st.info(f"턴: {turn_count}")

    with col3:
        st.metric(
            label=f"🔴 {p2['name']}",
            value=f"벽: {p2['walls_remaining']}",
            delta="현재 턴" if current_turn == 2 and status == "in_progress" else None
        )


def render_ascii_board(game_state: dict) -> str:
    """ASCII 보드 렌더링 (디버깅용)"""
    p1_pos = game_state["players"]["player1"]["position"]
    p2_pos = game_state["players"]["player2"]["position"]
    walls = game_state.get("walls", [])

    # 보드 초기화
    board = [["." for _ in range(9)] for _ in range(9)]

    # 플레이어 배치
    board[p1_pos["row"]][p1_pos["col"]] = "1"
    board[p2_pos["row"]][p2_pos["col"]] = "2"

    # ASCII 출력 생성
    lines = ["    0 1 2 3 4 5 6 7 8"]
    lines.append("   " + "-" * 19)

    for row in range(9):
        line = f"{row} | "
        for col in range(9):
            line += board[row][col] + " "
        lines.append(line)

    return "\n".join(lines)
