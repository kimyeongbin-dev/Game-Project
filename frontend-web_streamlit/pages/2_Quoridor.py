"""
Quoridor Game Page
쿼리도 게임 메인 페이지 - 통합 보드 UI
"""

import streamlit as st
import time
import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from games import GameState, SimpleAI

st.set_page_config(
    page_title="Quoridor - Game Hub",
    page_icon="🎯",
    layout="wide"
)


def init_session_state():
    """세션 상태 초기화"""
    if "game" not in st.session_state:
        st.session_state.game = None
    if "ai" not in st.session_state:
        st.session_state.ai = None
    if "wall_mode" not in st.session_state:
        st.session_state.wall_mode = False
    if "wall_orientation" not in st.session_state:
        st.session_state.wall_orientation = "horizontal"
    if "message" not in st.session_state:
        st.session_state.message = ""
    if "game_started" not in st.session_state:
        st.session_state.game_started = False


def create_new_game(player_name: str, difficulty: str):
    """새 게임 생성"""
    st.session_state.game = GameState(player1_name=player_name, player2_name="AI")
    st.session_state.ai = SimpleAI(difficulty=difficulty)
    st.session_state.wall_mode = False
    st.session_state.message = "게임이 시작되었습니다! 이동할 위치(⭕)를 클릭하세요."
    st.session_state.game_started = True


def get_game_state() -> dict:
    """현재 게임 상태 반환"""
    return st.session_state.game.to_dict()


def get_valid_moves() -> list:
    """유효한 이동 목록"""
    game = st.session_state.game
    moves = game.get_valid_pawn_moves()
    return [{"row": m.row, "col": m.col} for m in moves]


def move_pawn(row: int, col: int):
    """폰 이동"""
    game = st.session_state.game
    success, message = game.move_pawn(row, col)
    st.session_state.message = message
    return success


def place_wall(row: int, col: int, orientation: str):
    """벽 설치"""
    game = st.session_state.game
    success, message = game.place_wall(row, col, orientation)
    st.session_state.message = message
    return success


def ai_move():
    """AI 턴 수행"""
    game = st.session_state.game
    ai = st.session_state.ai
    action = ai.get_move(game)

    if action:
        if action.action_type.value == "move":
            success, message = game.move_pawn(action.row, action.col)
            st.session_state.message = f"AI가 ({action.row}, {action.col})로 이동했습니다."
        else:
            orient_kr = "수평" if action.orientation.value == "horizontal" else "수직"
            success, message = game.place_wall(
                action.row, action.col, action.orientation.value
            )
            st.session_state.message = f"AI가 ({action.row}, {action.col})에 {orient_kr} 벽을 설치했습니다."
        return success
    return False


def render_integrated_board(game_state: dict, valid_moves: list):
    """
    통합 보드 렌더링 - 셀, 벽, 벽 설치 위치를 모두 표시

    보드 구조 (17x17 그리드):
    - 홀수 행/열: 셀 (9개)
    - 짝수 행/열: 벽 위치
    """
    valid_positions = {(m["row"], m["col"]) for m in valid_moves}

    p1_pos = game_state["players"]["player1"]["position"]
    p2_pos = game_state["players"]["player2"]["position"]
    p1_position = (p1_pos["row"], p1_pos["col"])
    p2_position = (p2_pos["row"], p2_pos["col"])

    walls = game_state.get("walls", [])
    wall_mode = st.session_state.wall_mode
    wall_orientation = st.session_state.wall_orientation
    current_turn = game_state["current_turn"]
    status = game_state["status"]
    is_player_turn = current_turn == 1 and status == "in_progress"

    # 벽 위치를 빠르게 조회하기 위한 세트 생성
    # 수평 벽: (row, col)과 (row, col+1) 사이의 아래쪽 경계를 차단
    # 수직 벽: (row, col)과 (row+1, col) 사이의 오른쪽 경계를 차단
    h_wall_segments = set()  # (cell_row, cell_col) - 이 셀 아래에 수평 벽 세그먼트
    v_wall_segments = set()  # (cell_row, cell_col) - 이 셀 오른쪽에 수직 벽 세그먼트
    wall_centers = set()     # 벽 중심점 (row, col, orientation)

    for wall in walls:
        r, c, o = wall["row"], wall["col"], wall["orientation"]
        wall_centers.add((r, c, o))
        if o == "horizontal":
            # 수평 벽은 (r,c)-(r+1,c)와 (r,c+1)-(r+1,c+1) 사이를 차단
            h_wall_segments.add((r, c))
            h_wall_segments.add((r, c + 1))
        else:
            # 수직 벽은 (r,c)-(r,c+1)와 (r+1,c)-(r+1,c+1) 사이를 차단
            v_wall_segments.add((r, c))
            v_wall_segments.add((r + 1, c))

    # CSS 스타일
    st.markdown("""
    <style>
    .stButton > button {
        padding: 0 !important;
        min-height: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 17x17 그리드 생성 (9셀 + 8벽 공간)
    # 행 구조: 셀행, 수평벽행, 셀행, 수평벽행, ...

    for grid_row in range(17):
        cols = st.columns([0.3] + [1 if grid_row % 2 == 0 else 0.3] * 17)

        # 행 번호 표시 (셀 행만)
        if grid_row % 2 == 0:
            cell_row = grid_row // 2
            cols[0].write(f"**{cell_row}**")
        else:
            cols[0].write("")

        for grid_col in range(17):
            col_idx = grid_col + 1

            if grid_row % 2 == 0 and grid_col % 2 == 0:
                # 셀 위치 (홀수x홀수 in 0-indexed: 0,2,4,6,8,10,12,14,16)
                cell_row = grid_row // 2
                cell_col = grid_col // 2
                position = (cell_row, cell_col)

                # 셀 내용 결정
                if position == p1_position:
                    label = "🔵"
                elif position == p2_position:
                    label = "🔴"
                elif position in valid_positions and not wall_mode and is_player_turn:
                    label = "⭕"
                else:
                    label = "·"

                is_valid = position in valid_positions and not wall_mode and is_player_turn
                btn_type = "primary" if is_valid else "secondary"

                with cols[col_idx]:
                    if st.button(label, key=f"c_{cell_row}_{cell_col}",
                                use_container_width=True, type=btn_type,
                                disabled=not is_valid):
                        if is_valid:
                            if move_pawn(cell_row, cell_col):
                                st.rerun()

            elif grid_row % 2 == 0 and grid_col % 2 == 1:
                # 수직 벽 위치 (셀 사이 세로)
                cell_row = grid_row // 2
                wall_col = grid_col // 2  # 0~7

                # 이 위치에 벽이 있는지 확인
                has_wall = (cell_row, wall_col) in v_wall_segments

                with cols[col_idx]:
                    if has_wall:
                        st.markdown("**┃**")
                    elif wall_mode and wall_orientation == "vertical" and is_player_turn:
                        # 벽 설치 가능 위치 표시
                        if cell_row < 8 and wall_col < 8:
                            # 이 위치에 벽을 설치할 수 있는지 확인
                            can_place = (cell_row, wall_col, "vertical") not in wall_centers
                            if can_place and st.button("│", key=f"vw_{cell_row}_{wall_col}"):
                                if place_wall(cell_row, wall_col, "vertical"):
                                    st.session_state.wall_mode = False
                                    st.rerun()
                    else:
                        st.write("")

            elif grid_row % 2 == 1 and grid_col % 2 == 0:
                # 수평 벽 위치 (셀 사이 가로)
                wall_row = grid_row // 2  # 0~7
                cell_col = grid_col // 2

                has_wall = (wall_row, cell_col) in h_wall_segments

                with cols[col_idx]:
                    if has_wall:
                        st.markdown("**━**")
                    elif wall_mode and wall_orientation == "horizontal" and is_player_turn:
                        if wall_row < 8 and cell_col < 8:
                            can_place = (wall_row, cell_col, "horizontal") not in wall_centers
                            if can_place and st.button("─", key=f"hw_{wall_row}_{cell_col}"):
                                if place_wall(wall_row, cell_col, "horizontal"):
                                    st.session_state.wall_mode = False
                                    st.rerun()
                    else:
                        st.write("")

            else:
                # 교차점 (벽이 만나는 곳)
                with cols[col_idx]:
                    st.write("")


def render_simple_board(game_state: dict, valid_moves: list):
    """
    간단한 통합 보드 - 벽을 시각적으로 표시
    """
    valid_positions = {(m["row"], m["col"]) for m in valid_moves}

    p1_pos = game_state["players"]["player1"]["position"]
    p2_pos = game_state["players"]["player2"]["position"]
    p1_position = (p1_pos["row"], p1_pos["col"])
    p2_position = (p2_pos["row"], p2_pos["col"])

    walls = game_state.get("walls", [])
    wall_mode = st.session_state.wall_mode
    wall_orientation = st.session_state.wall_orientation
    current_turn = game_state["current_turn"]
    status = game_state["status"]
    is_player_turn = current_turn == 1 and status == "in_progress"

    # 벽 세그먼트 계산
    h_walls = set()  # (row, col) - row행 아래, col열에 수평벽
    v_walls = set()  # (row, col) - row행, col열 오른쪽에 수직벽

    for wall in walls:
        r, c, o = wall["row"], wall["col"], wall["orientation"]
        if o == "horizontal":
            h_walls.add((r, c))
            h_walls.add((r, c + 1))
        else:
            v_walls.add((r, c))
            v_walls.add((r + 1, c))

    # 열 헤더
    header = st.columns([0.5] + [1] * 9)
    header[0].write("")
    for c in range(9):
        header[c + 1].write(f"**{c}**")

    # 보드 렌더링
    for row in range(9):
        # 셀 행
        cols = st.columns([0.5] + [1] * 9)
        cols[0].write(f"**{row}**")

        for col in range(9):
            position = (row, col)

            # 셀 스타일 결정
            if position == p1_position:
                label = "🔵"
            elif position == p2_position:
                label = "🔴"
            elif position in valid_positions and not wall_mode and is_player_turn:
                label = "⭕"
            elif row == 0:
                label = "🏁" if col == 4 else "·"
            elif row == 8:
                label = "🏁" if col == 4 else "·"
            else:
                label = "·"

            # 벽 표시를 위한 이모지 추가
            right_wall = "┃" if (row, col) in v_walls else ""
            bottom_wall = "━" if (row, col) in h_walls else ""

            is_valid = position in valid_positions and not wall_mode and is_player_turn

            with cols[col + 1]:
                # 벽 표시
                wall_indicator = ""
                if (row, col) in v_walls and col < 8:
                    wall_indicator += "▌"
                if (row, col) in h_walls and row < 8:
                    wall_indicator += "▄"

                btn_label = label
                if wall_indicator:
                    btn_label = f"{label}"

                btn_type = "primary" if is_valid else "secondary"

                if st.button(btn_label, key=f"cell_{row}_{col}",
                            use_container_width=True, type=btn_type,
                            disabled=wall_mode or not is_player_turn):
                    if is_valid:
                        if move_pawn(row, col):
                            st.rerun()

        # 수평 벽 행 (마지막 행 제외)
        if row < 8:
            wall_cols = st.columns([0.5] + [1] * 9)
            wall_cols[0].write("")
            for col in range(9):
                with wall_cols[col + 1]:
                    has_h_wall = (row, col) in h_walls
                    if has_h_wall:
                        st.markdown("<div style='background-color: #8B4513; height: 6px; margin: 0;'></div>",
                                   unsafe_allow_html=True)
                    else:
                        st.write("")


def render_visual_board(game_state: dict, valid_moves: list):
    """
    시각적 보드 렌더링 - HTML/CSS 기반
    """
    valid_positions = {(m["row"], m["col"]) for m in valid_moves}

    p1_pos = game_state["players"]["player1"]["position"]
    p2_pos = game_state["players"]["player2"]["position"]

    walls = game_state.get("walls", [])
    wall_mode = st.session_state.wall_mode
    wall_orientation = st.session_state.wall_orientation
    current_turn = game_state["current_turn"]
    status = game_state["status"]
    is_player_turn = current_turn == 1 and status == "in_progress"

    # 벽 세그먼트 계산
    h_walls = set()
    v_walls = set()

    for wall in walls:
        r, c, o = wall["row"], wall["col"], wall["orientation"]
        if o == "horizontal":
            h_walls.add((r, c))
            h_walls.add((r, c + 1))
        else:
            v_walls.add((r, c))
            v_walls.add((r + 1, c))

    # 보드 HTML 생성
    board_html = """
    <style>
    .quoridor-board {
        display: grid;
        grid-template-columns: repeat(17, 1fr);
        gap: 0;
        max-width: 500px;
        margin: 0 auto;
        background: #DEB887;
        padding: 10px;
        border-radius: 8px;
    }
    .cell {
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        background: #F5DEB3;
        border: 1px solid #D2B48C;
    }
    .h-wall-space {
        height: 8px;
        background: transparent;
    }
    .v-wall-space {
        width: 8px;
        background: transparent;
    }
    .wall-h {
        background: #8B4513 !important;
    }
    .wall-v {
        background: #8B4513 !important;
    }
    .intersection {
        width: 8px;
        height: 8px;
        background: transparent;
    }
    .valid-move {
        background: #90EE90;
        cursor: pointer;
    }
    </style>
    <div class="quoridor-board">
    """

    for grid_row in range(17):
        for grid_col in range(17):
            if grid_row % 2 == 0 and grid_col % 2 == 0:
                # 셀
                cell_row, cell_col = grid_row // 2, grid_col // 2
                content = ""
                css_class = "cell"

                if (cell_row, cell_col) == (p1_pos["row"], p1_pos["col"]):
                    content = "🔵"
                elif (cell_row, cell_col) == (p2_pos["row"], p2_pos["col"]):
                    content = "🔴"
                elif (cell_row, cell_col) in valid_positions and is_player_turn:
                    content = "⭕"
                    css_class += " valid-move"

                board_html += f'<div class="{css_class}">{content}</div>'

            elif grid_row % 2 == 0 and grid_col % 2 == 1:
                # 수직 벽 공간
                cell_row = grid_row // 2
                wall_col = grid_col // 2
                has_wall = (cell_row, wall_col) in v_walls
                css_class = "v-wall-space wall-v" if has_wall else "v-wall-space"
                board_html += f'<div class="{css_class}"></div>'

            elif grid_row % 2 == 1 and grid_col % 2 == 0:
                # 수평 벽 공간
                wall_row = grid_row // 2
                cell_col = grid_col // 2
                has_wall = (wall_row, cell_col) in h_walls
                css_class = "h-wall-space wall-h" if has_wall else "h-wall-space"
                board_html += f'<div class="{css_class}"></div>'

            else:
                # 교차점
                board_html += '<div class="intersection"></div>'

    board_html += "</div>"

    st.markdown(board_html, unsafe_allow_html=True)

    # 버튼 기반 인터랙션 (HTML 클릭 이벤트 대신)
    st.write("")

    if is_player_turn and not wall_mode:
        st.write("**이동할 위치 선택:**")
        move_cols = st.columns(min(len(valid_moves), 6)) if valid_moves else []
        for i, move in enumerate(valid_moves[:6]):
            with move_cols[i % 6]:
                if st.button(f"({move['row']},{move['col']})", key=f"mv_{move['row']}_{move['col']}"):
                    if move_pawn(move['row'], move['col']):
                        st.rerun()
        if len(valid_moves) > 6:
            move_cols2 = st.columns(min(len(valid_moves) - 6, 6))
            for i, move in enumerate(valid_moves[6:]):
                with move_cols2[i]:
                    if st.button(f"({move['row']},{move['col']})", key=f"mv2_{move['row']}_{move['col']}"):
                        if move_pawn(move['row'], move['col']):
                            st.rerun()


def render_compact_board(game_state: dict, valid_moves: list):
    """
    컴팩트 보드 - HTML/CSS 기반으로 벽을 연속된 막대로 표시
    """
    valid_positions = {(m["row"], m["col"]) for m in valid_moves}

    p1_pos = game_state["players"]["player1"]["position"]
    p2_pos = game_state["players"]["player2"]["position"]

    walls = game_state.get("walls", [])
    wall_mode = st.session_state.wall_mode
    wall_orientation = st.session_state.wall_orientation
    current_turn = game_state["current_turn"]
    status = game_state["status"]
    is_player_turn = current_turn == 1 and status == "in_progress"

    # 벽 원본 위치 (연속 벽 렌더링용)
    h_wall_origins = set()  # (row, col) - 수평 벽 시작점
    v_wall_origins = set()  # (row, col) - 수직 벽 시작점

    for wall in walls:
        r, c, o = wall["row"], wall["col"], wall["orientation"]
        if o == "horizontal":
            h_wall_origins.add((r, c))
        else:
            v_wall_origins.add((r, c))

    # CSS 스타일
    st.markdown("""
    <style>
    .board-container {
        display: inline-block;
        background: #DEB887;
        padding: 15px;
        border-radius: 10px;
        border: 3px solid #8B4513;
    }
    .board-grid {
        display: grid;
        grid-template-columns: repeat(17, auto);
        gap: 0;
    }
    .cell {
        width: 45px;
        height: 45px;
        background: #F5DEB3;
        border: 1px solid #D2B48C;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
    }
    .cell-valid {
        background: #90EE90;
        cursor: pointer;
    }
    .cell-goal {
        background: #FFE4B5;
    }
    .h-gap {
        width: 8px;
        height: 45px;
        background: #DEB887;
    }
    .v-gap {
        width: 45px;
        height: 8px;
        background: #DEB887;
    }
    .intersection {
        width: 8px;
        height: 8px;
        background: #DEB887;
    }
    .wall-h {
        background: #8B4513 !important;
    }
    .wall-v {
        background: #8B4513 !important;
    }
    .wall-center {
        background: #8B4513 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 보드 HTML 생성
    board_html = '<div class="board-container"><div class="board-grid">'

    for grid_row in range(17):
        for grid_col in range(17):
            if grid_row % 2 == 0 and grid_col % 2 == 0:
                # 셀 (9x9)
                cell_row, cell_col = grid_row // 2, grid_col // 2
                css_class = "cell"
                content = ""

                if (cell_row, cell_col) == (p1_pos["row"], p1_pos["col"]):
                    content = "🔵"
                elif (cell_row, cell_col) == (p2_pos["row"], p2_pos["col"]):
                    content = "🔴"
                elif (cell_row, cell_col) in valid_positions and not wall_mode and is_player_turn:
                    content = "⭕"
                    css_class += " cell-valid"
                elif cell_row == 0 or cell_row == 8:
                    css_class += " cell-goal"

                board_html += f'<div class="{css_class}">{content}</div>'

            elif grid_row % 2 == 0 and grid_col % 2 == 1:
                # 수직 벽 공간 (셀 사이 세로)
                cell_row = grid_row // 2
                wall_col = grid_col // 2

                # 이 위치를 지나는 수직 벽이 있는지 확인
                # 수직 벽 (r, c)는 (r, c)와 (r+1, c) 사이를 차단
                has_wall = (cell_row, wall_col) in v_wall_origins or (cell_row - 1, wall_col) in v_wall_origins
                css_class = "h-gap wall-v" if has_wall else "h-gap"
                board_html += f'<div class="{css_class}"></div>'

            elif grid_row % 2 == 1 and grid_col % 2 == 0:
                # 수평 벽 공간 (셀 사이 가로)
                wall_row = grid_row // 2
                cell_col = grid_col // 2

                # 이 위치를 지나는 수평 벽이 있는지 확인
                # 수평 벽 (r, c)는 (r, c)와 (r, c+1) 아래를 차단
                has_wall = (wall_row, cell_col) in h_wall_origins or (wall_row, cell_col - 1) in h_wall_origins
                css_class = "v-gap wall-h" if has_wall else "v-gap"
                board_html += f'<div class="{css_class}"></div>'

            else:
                # 교차점 (벽이 만나는 곳)
                int_row = grid_row // 2
                int_col = grid_col // 2

                # 이 교차점을 지나는 벽이 있는지 확인
                has_h_wall = (int_row, int_col) in h_wall_origins
                has_v_wall = (int_row, int_col) in v_wall_origins

                css_class = "intersection"
                if has_h_wall or has_v_wall:
                    css_class += " wall-center"
                board_html += f'<div class="{css_class}"></div>'

    board_html += '</div></div>'
    st.markdown(board_html, unsafe_allow_html=True)

    st.write("")

    # 인터랙션 버튼들
    if is_player_turn:
        if not wall_mode:
            # 이동 모드 - 유효한 이동 위치 버튼
            if valid_moves:
                st.write("**이동할 위치 선택:**")
                num_cols = min(len(valid_moves), 5)
                move_cols = st.columns(num_cols)
                for i, move in enumerate(valid_moves):
                    with move_cols[i % num_cols]:
                        if st.button(f"({move['row']}, {move['col']})", key=f"mv_{move['row']}_{move['col']}",
                                   use_container_width=True, type="primary"):
                            if move_pawn(move['row'], move['col']):
                                st.rerun()
        else:
            # 벽 설치 모드
            st.write(f"**벽 설치 위치 선택** ({'수평 ━━' if wall_orientation == 'horizontal' else '수직 ┃┃'}):")

            # 벽 설치 가능 위치 계산
            existing_walls = {(w["row"], w["col"], w["orientation"]) for w in walls}

            # 8x8 그리드로 벽 설치 위치 표시
            for wr in range(8):
                wall_cols = st.columns(8)
                for wc in range(8):
                    with wall_cols[wc]:
                        # 이미 같은 위치에 벽이 있거나 겹치는지 확인
                        is_blocked = (wr, wc, wall_orientation) in existing_walls
                        # 교차 검사 (같은 중심점의 다른 방향 벽)
                        other_orient = "vertical" if wall_orientation == "horizontal" else "horizontal"
                        is_blocked = is_blocked or (wr, wc, other_orient) in existing_walls

                        if is_blocked:
                            st.button("✕", key=f"w_{wr}_{wc}", disabled=True, use_container_width=True)
                        else:
                            label = "━" if wall_orientation == "horizontal" else "┃"
                            if st.button(label, key=f"w_{wr}_{wc}", use_container_width=True):
                                if place_wall(wr, wc, wall_orientation):
                                    st.session_state.wall_mode = False
                                    st.rerun()


def main():
    """메인 함수"""
    init_session_state()

    st.title("🎯 쿼리도 (Quoridor)")

    # 사이드바
    with st.sidebar:
        st.header("🎮 게임 설정")

        if not st.session_state.game_started:
            player_name = st.text_input("플레이어 이름", value="Player")
            difficulty = st.select_slider(
                "AI 난이도",
                options=["easy", "normal", "hard"],
                value="normal",
                format_func=lambda x: {"easy": "쉬움", "normal": "보통", "hard": "어려움"}[x]
            )

            if st.button("🚀 게임 시작", use_container_width=True, type="primary"):
                create_new_game(player_name, difficulty)
                st.rerun()
        else:
            if st.button("🔄 새 게임", use_container_width=True):
                st.session_state.game_started = False
                st.session_state.game = None
                st.rerun()

        st.markdown("---")

        # 게임 규칙
        with st.expander("📖 게임 규칙"):
            st.markdown("""
            **목표**: 반대편 끝에 먼저 도달!

            - 🔵 **당신**: 하단 → 상단(row=0)
            - 🔴 **AI**: 상단 → 하단(row=8)

            **턴마다:**
            1. 이동 (⭕ 위치 클릭)
            2. 또는 벽 설치

            **규칙:**
            - 벽은 2칸 길이
            - 경로 완전 차단 불가
            """)

    if not st.session_state.game_started:
        st.info("👈 사이드바에서 게임을 시작하세요!")
        return

    # 게임 상태
    game_state = get_game_state()
    status = game_state["status"]
    current_turn = game_state["current_turn"]
    is_player_turn = current_turn == 1 and status == "in_progress"

    # 게임 정보
    col1, col2, col3 = st.columns(3)
    p1 = game_state["players"]["player1"]
    p2 = game_state["players"]["player2"]

    with col1:
        turn_indicator = " ◀" if current_turn == 1 and status == "in_progress" else ""
        st.metric(f"🔵 {p1['name']}{turn_indicator}", f"벽: {p1['walls_remaining']}개")

    with col2:
        if status == "finished":
            winner = game_state.get("winner")
            winner_name = game_state["players"][f"player{winner}"]["name"]
            if winner == 1:
                st.success(f"🎉 {winner_name} 승리!")
            else:
                st.error(f"😔 {winner_name} 승리...")
        else:
            st.info(f"턴: {game_state['turn_count']}")

    with col3:
        turn_indicator = " ◀" if current_turn == 2 and status == "in_progress" else ""
        st.metric(f"🔴 {p2['name']}{turn_indicator}", f"벽: {p2['walls_remaining']}개")

    # 메시지
    if st.session_state.message:
        st.info(st.session_state.message)

    st.markdown("---")

    # 게임 컨트롤
    if is_player_turn:
        ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns(4)

        with ctrl_col1:
            wall_mode = st.session_state.wall_mode
            if p1["walls_remaining"] > 0:
                mode_label = "🚶 이동 모드" if wall_mode else "🧱 벽 설치 모드"
                if st.button(mode_label, use_container_width=True,
                           type="primary" if not wall_mode else "secondary"):
                    st.session_state.wall_mode = not wall_mode
                    st.rerun()
            else:
                st.button("🧱 벽 없음", disabled=True, use_container_width=True)

        if st.session_state.wall_mode:
            with ctrl_col2:
                if st.button("━ 수평", use_container_width=True,
                           type="primary" if st.session_state.wall_orientation == "horizontal" else "secondary"):
                    st.session_state.wall_orientation = "horizontal"
                    st.rerun()

            with ctrl_col3:
                if st.button("┃ 수직", use_container_width=True,
                           type="primary" if st.session_state.wall_orientation == "vertical" else "secondary"):
                    st.session_state.wall_orientation = "vertical"
                    st.rerun()

            with ctrl_col4:
                st.caption(f"방향: {'수평━' if st.session_state.wall_orientation == 'horizontal' else '수직┃'}")

    st.markdown("---")

    # 보드 렌더링
    valid_moves = get_valid_moves() if is_player_turn else []
    render_compact_board(game_state, valid_moves)

    # 설치된 벽 정보
    walls = game_state.get("walls", [])
    if walls:
        with st.expander(f"🧱 설치된 벽 목록 ({len(walls)}개)"):
            for i, wall in enumerate(walls):
                orient = "수평━" if wall["orientation"] == "horizontal" else "수직┃"
                st.write(f"{i+1}. 위치 ({wall['row']}, {wall['col']}) - {orient}")

    # AI 턴
    if status == "in_progress" and current_turn == 2:
        st.warning("🔴 AI 차례입니다...")
        time.sleep(0.8)
        ai_move()
        st.rerun()


if __name__ == "__main__":
    main()
