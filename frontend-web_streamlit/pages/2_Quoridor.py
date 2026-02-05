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


def render_interactive_board(game_state: dict, valid_moves: list):
    """
    통합 인터랙티브 보드 - Flutter 스타일 HTML 디자인 + 셀 클릭 기능
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
    h_wall_segments = set()
    v_wall_segments = set()
    wall_centers = set()

    for wall in walls:
        r, c, o = wall["row"], wall["col"], wall["orientation"]
        wall_centers.add((r, c))
        if o == "horizontal":
            h_wall_segments.add(f"{r},{c}")
            h_wall_segments.add(f"{r},{c+1}")
        else:
            v_wall_segments.add(f"{r},{c}")
            v_wall_segments.add(f"{r+1},{c}")

    # CSS 스타일 - Flutter 디자인 유지
    cell_size = 44
    gap_size = 6

    st.markdown(f"""
    <style>
    .unified-board {{
        display: inline-grid;
        grid-template-columns: {' '.join([f'{cell_size}px' if i % 2 == 0 else f'{gap_size}px' for i in range(17)])};
        grid-template-rows: {' '.join([f'{cell_size}px' if i % 2 == 0 else f'{gap_size}px' for i in range(17)])};
        gap: 0;
        background: linear-gradient(145deg, #d4a574, #c49a6c);
        padding: 12px;
        border-radius: 12px;
        border: 3px solid #8B4513;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }}
    .board-cell {{
        background: linear-gradient(145deg, #fff8dc, #f5deb3);
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 22px;
        border: 1px solid #d2b48c;
    }}
    .board-cell.valid {{
        background: linear-gradient(145deg, #98fb98, #7ccd7c);
        box-shadow: 0 0 8px rgba(0,200,0,0.4);
        animation: pulse 1.5s infinite;
    }}
    .board-cell.goal-top {{
        background: linear-gradient(145deg, #e6f3ff, #cce5ff);
    }}
    .board-cell.goal-bottom {{
        background: linear-gradient(145deg, #ffe6e6, #ffcccc);
    }}
    .wall-h {{
        background: #654321;
        border-radius: 2px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.3);
    }}
    .wall-v {{
        background: #654321;
        border-radius: 2px;
        box-shadow: 1px 0 2px rgba(0,0,0,0.3);
    }}
    .wall-gap {{
        background: transparent;
    }}
    .wall-gap.placeable {{
        background: rgba(139, 69, 19, 0.2);
        border-radius: 2px;
        border: 1px dashed #8B4513;
    }}
    .intersection {{
        background: transparent;
    }}
    .intersection.has-wall {{
        background: #654321;
        border-radius: 2px;
    }}
    .player-token {{
        width: 32px;
        height: 32px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: bold;
        color: white;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    }}
    .player-token.p1 {{
        background: linear-gradient(145deg, #4a90d9, #357abd);
    }}
    .player-token.p2 {{
        background: linear-gradient(145deg, #e05555, #c94444);
    }}
    .player-token.current {{
        animation: pulse 0.8s infinite alternate;
    }}
    @keyframes pulse {{
        from {{ transform: scale(1); }}
        to {{ transform: scale(1.08); }}
    }}
    .valid-dot {{
        width: 12px;
        height: 12px;
        background: #228b22;
        border-radius: 50%;
        box-shadow: 0 0 6px rgba(34,139,34,0.5);
    }}

    /* 클릭 그리드 스타일 */
    .click-grid {{
        display: inline-grid;
        grid-template-columns: repeat(9, {cell_size}px);
        grid-template-rows: repeat(9, {cell_size}px);
        gap: {gap_size}px;
        margin-top: -{ (cell_size + gap_size) * 9 - gap_size + 24 }px;
        margin-left: 12px;
        position: relative;
    }}
    .click-cell {{
        width: {cell_size}px;
        height: {cell_size}px;
        background: transparent;
        border: none;
        cursor: pointer;
        border-radius: 4px;
    }}
    .click-cell:hover {{
        background: rgba(255,255,255,0.2);
    }}
    .click-cell.valid:hover {{
        background: rgba(0,200,0,0.3);
    }}
    .click-cell:disabled {{
        cursor: default;
    }}
    .click-cell:disabled:hover {{
        background: transparent;
    }}
    </style>
    """, unsafe_allow_html=True)

    # HTML 보드 생성 (시각적 표시)
    board_html = '<div style="display:flex;justify-content:center;"><div class="unified-board">'

    for grid_row in range(17):
        for grid_col in range(17):
            is_cell_row = grid_row % 2 == 0
            is_cell_col = grid_col % 2 == 0

            if is_cell_row and is_cell_col:
                cell_row, cell_col = grid_row // 2, grid_col // 2
                position = (cell_row, cell_col)

                css_class = "board-cell"
                content = ""

                if position == (p1_pos["row"], p1_pos["col"]):
                    turn_class = " current" if current_turn == 1 and status == "in_progress" else ""
                    content = f'<div class="player-token p1{turn_class}">P1</div>'
                elif position == (p2_pos["row"], p2_pos["col"]):
                    turn_class = " current" if current_turn == 2 and status == "in_progress" else ""
                    content = f'<div class="player-token p2{turn_class}">AI</div>'
                elif position in valid_positions and not wall_mode and is_player_turn:
                    css_class += " valid"
                    content = '<div class="valid-dot"></div>'
                elif cell_row == 0:
                    css_class += " goal-top"
                    content = '<span style="color:#4a90d9;font-size:14px;">▲</span>'
                elif cell_row == 8:
                    css_class += " goal-bottom"
                    content = '<span style="color:#c94444;font-size:14px;">▼</span>'

                board_html += f'<div class="{css_class}">{content}</div>'

            elif is_cell_row and not is_cell_col:
                cell_row = grid_row // 2
                wall_col = grid_col // 2
                has_wall = f"{cell_row},{wall_col}" in v_wall_segments

                if has_wall:
                    board_html += '<div class="wall-v"></div>'
                elif wall_mode and wall_orientation == "vertical" and is_player_turn:
                    if cell_row < 8 and wall_col < 8 and (cell_row, wall_col) not in wall_centers:
                        board_html += '<div class="wall-gap placeable"></div>'
                    else:
                        board_html += '<div class="wall-gap"></div>'
                else:
                    board_html += '<div class="wall-gap"></div>'

            elif not is_cell_row and is_cell_col:
                wall_row = grid_row // 2
                cell_col = grid_col // 2
                has_wall = f"{wall_row},{cell_col}" in h_wall_segments

                if has_wall:
                    board_html += '<div class="wall-h"></div>'
                elif wall_mode and wall_orientation == "horizontal" and is_player_turn:
                    if wall_row < 8 and cell_col < 8 and (wall_row, cell_col) not in wall_centers:
                        board_html += '<div class="wall-gap placeable"></div>'
                    else:
                        board_html += '<div class="wall-gap"></div>'
                else:
                    board_html += '<div class="wall-gap"></div>'

            else:
                int_row, int_col = grid_row // 2, grid_col // 2
                has_h = any(w["row"] == int_row and w["col"] == int_col and w["orientation"] == "horizontal" for w in walls)
                has_v = any(w["row"] == int_row and w["col"] == int_col and w["orientation"] == "vertical" for w in walls)

                if has_h or has_v:
                    board_html += '<div class="intersection has-wall"></div>'
                else:
                    board_html += '<div class="intersection"></div>'

    board_html += '</div></div>'
    st.markdown(board_html, unsafe_allow_html=True)

    # 클릭 영역 (9x9 투명 버튼 그리드) - 이동 모드
    if is_player_turn and not wall_mode:
        st.write("")
        cols = st.columns([1, 6, 1])  # 중앙 정렬
        with cols[1]:
            for row in range(9):
                btn_cols = st.columns(9)
                for col in range(9):
                    with btn_cols[col]:
                        is_valid = (row, col) in valid_positions
                        is_p1 = (row, col) == (p1_pos["row"], p1_pos["col"])
                        is_p2 = (row, col) == (p2_pos["row"], p2_pos["col"])

                        if is_valid:
                            if st.button("●", key=f"m_{row}_{col}", type="primary",
                                       use_container_width=True):
                                if move_pawn(row, col):
                                    st.rerun()
                        elif is_p1:
                            st.button("P1", key=f"m_{row}_{col}", disabled=True,
                                    use_container_width=True)
                        elif is_p2:
                            st.button("AI", key=f"m_{row}_{col}", disabled=True,
                                    use_container_width=True)
                        else:
                            st.button("", key=f"m_{row}_{col}", disabled=True,
                                    use_container_width=True)

    # 벽 설치 모드 - 8x8 그리드
    elif is_player_turn and wall_mode:
        orient_label = "수평 ━━" if wall_orientation == "horizontal" else "수직 ┃┃"
        st.markdown(f"##### 벽 설치 위치 선택 ({orient_label})")

        for wr in range(8):
            wcols = st.columns(8)
            for wc in range(8):
                with wcols[wc]:
                    is_blocked = (wr, wc) in wall_centers
                    if is_blocked:
                        st.button("✕", key=f"w_{wr}_{wc}", disabled=True,
                                 use_container_width=True)
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
    render_interactive_board(game_state, valid_moves)

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
