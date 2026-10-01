"""
좌석 수 일반화 테스트 — M3 1단계 완료 판정

모든 테스트가 duel(2) · trio(3) · quad(4) 에서 돈다. quad 는 conftest 의 seat_mode
픽스처가 배치 테이블에 행을 추가하는 것으로만 만들어진다. 엔진 코드에 4인용 분기가
없다는 것을 이 파일이 증명한다 (docs/api/platform.md §5 확장성 원칙).
"""

import json
import random
import re
from pathlib import Path

import pytest

from app.games.maze.ai.simple_ai import SimpleAI
from app.games.maze.core.board import Goal, Position
from app.games.maze.core.game_state import GameState, EndReason, ActionType
from app.games.maze.core.move_validator import Rejection
from app.games.maze.core.pathfinder import Pathfinder
from app.games.maze.core.wall import Wall, Orientation


def new_game(mode: str, seed: int = 0) -> GameState:
    return GameState(mode, rng=random.Random(seed))


def step_one(game: GameState) -> None:
    """현재 좌석이 첫 번째 합법 이동을 한다"""
    target = game.get_valid_pawn_moves()[0]
    assert game.move(game.current_seat_no, target.row, target.col) is None


def trap_ready(game: GameState, target_seat: int) -> None:
    """target_seat 를 왼쪽 하단 주머니 (8,0)-(7,0) 에 넣고 출구 하나만 남긴다.

    남은 출구 (7,0)→(6,0) 은 가로벽 (6,0) 이 닫는다. 기하를 고정하려고 목표를
    row 0 으로 두고, 다른 좌석은 중앙에 겹쳐 세운다 (중첩 허용 — §5).
    """
    for p in game.seats:
        p.position = Position(4, 4)
    target = game.seat(target_seat)
    target.position = Position(8, 0)
    target.goals = (Goal("row", 0),)
    assert game.wall_manager.add_wall(Wall(7, 0, Orientation.VERTICAL)) is True


# ----- 배치 -----

def test_initial_layout(seat_mode):
    mode, n = seat_mode
    game = new_game(mode)

    assert [p.seat_no for p in game.seats] == list(range(1, n + 1))
    assert len({p.position for p in game.seats}) == n
    for p in game.seats:
        assert len(p.goals) >= 1
        assert not p.has_reached_goal()
        assert game.get_player_distance_to_goal(p.seat_no) == 8


# ----- 턴 순환 -----

def test_rotation_returns_to_seat1(seat_mode):
    mode, n = seat_mode
    game = new_game(mode)

    for expected in range(1, n + 1):
        assert game.current_seat_no == expected
        step_one(game)

    assert game.current_seat_no == 1
    assert all(p.turns_taken == 1 for p in game.seats)
    assert game.turn_count == n


def test_eliminated_middle_seat_is_skipped(seat_mode):
    mode, n = seat_mode
    if n < 3:
        pytest.skip("중간 좌석이 없다 — 2인은 한 명 탈락이 곧 종료")
    game = new_game(mode)

    assert game.eliminate(2, "surrender") is None
    step_one(game)

    assert game.current_seat_no == 3


def test_eliminating_current_seat_passes_turn(seat_mode):
    mode, n = seat_mode
    game = new_game(mode)

    assert game.eliminate(1, "time_forfeit") is None

    if n == 2:
        assert game.end_reason == EndReason.LAST_STANDING
    else:
        assert game.current_seat_no == 2
        assert not game.is_finished


def test_last_standing(seat_mode):
    mode, n = seat_mode
    game = new_game(mode)

    for seat_no in range(1, n):
        assert not game.is_finished
        assert game.eliminate(seat_no, "disconnect_forfeit") is None

    assert game.end_reason == EndReason.LAST_STANDING
    assert game.winner_seat_no == n
    assert [game.seat(s).eliminated_order for s in range(1, n)] == list(range(1, n))
    assert game.move(n, 0, 0) == Rejection.GAME_ALREADY_ENDED


# ----- 이동·목표 -----

def test_every_goal_of_every_seat_ends_the_game(seat_mode):
    """좌석마다, 목표 원소마다 — 꼭짓점 좌석은 col 목표로도 끝난다"""
    mode, n = seat_mode

    for seat_no in range(1, n + 1):
        for goal in new_game(mode).seat(seat_no).goals:
            game = new_game(mode)
            player = game.seat(seat_no)
            near = goal.value - 1 if goal.value > 0 else 1
            if goal.axis == "row":
                player.position, target = Position(near, 4), Position(goal.value, 4)
            else:
                player.position, target = Position(4, near), Position(4, goal.value)
            game.current_seat_no = seat_no

            assert game.move(seat_no, target.row, target.col) is None
            assert game.end_reason == EndReason.GOAL_REACHED
            assert game.winner_seat_no == seat_no


def test_pieces_overlap(seat_mode):
    """다른 말이 선 칸으로 그냥 들어간다 (§5)"""
    mode, n = seat_mode
    game = new_game(mode)
    target = game.get_valid_pawn_moves()[0]
    for p in game.seats[1:]:
        p.position = target

    assert game.move(1, target.row, target.col) is None
    assert {p.position for p in game.seats} == {target}


# ----- 벽 검증 -----

def test_path_guarantee_covers_survivors_only(seat_mode):
    mode, n = seat_mode
    game = new_game(mode)
    trap_ready(game, n)

    assert game.place_wall(1, 6, 0, "horizontal") == Rejection.WALL_BLOCKS_PATH

    if n >= 3:
        game.eliminate(n, "surrender")
        # 탈락자는 검증 대상이 아니다 — 갇혀도 벽은 놓인다
        assert game.place_wall(1, 6, 0, "horizontal") is None


def test_probe_counter_shared_and_locks(seat_mode):
    """겹침과 경로 차단을 같은 카운터로 세고, 3회째에 잠근다 (§7)"""
    mode, n = seat_mode
    game = new_game(mode)
    trap_ready(game, n)
    game.wall_manager.add_wall(Wall(2, 2, Orientation.HORIZONTAL))

    assert game.place_wall(1, 2, 2, "vertical") == Rejection.INVALID_WALL_POSITION    # 교차
    assert game.place_wall(1, 9, 9, "vertical") == Rejection.INVALID_WALL_POSITION    # 범위 밖: 안 셈
    assert game.place_wall(1, 6, 0, "horizontal") == Rejection.WALL_BLOCKS_PATH      # 차단
    assert game.wall_rejections == 2
    assert game.place_wall(1, 2, 2, "horizontal") == Rejection.INVALID_WALL_POSITION  # 3회째 → 잠금
    assert game.place_wall(1, 4, 6, "vertical") == Rejection.PROBE_LIMIT_EXCEEDED

    step_one(game)
    assert game.wall_rejections == 0
    assert game.place_wall(2, 4, 6, "vertical") is None


# ----- 순위 -----

def test_standings_goal_survivors_eliminated(seat_mode):
    """도달자 > 생존자(거리 짧은 순, 동률 공동) > 탈락자"""
    mode, n = seat_mode
    game = new_game(mode)
    if n >= 3:
        game.eliminate(2, "surrender")
        last = game.seat(n)
        last.position = Pathfinder.find_shortest_path(last.position, last.goals, game.wall_manager)[1]

    winner = game.seat(1)
    winner.position = Pathfinder.find_shortest_path(winner.position, winner.goals, game.wall_manager)[-2]
    goal_cell = Pathfinder.find_shortest_path(winner.position, winner.goals, game.wall_manager)[-1]
    assert game.move(1, goal_cell.row, goal_cell.col) is None

    ranks = {r["seat_no"]: r["rank"] for r in game.standings()}
    if n == 2:
        assert ranks == {1: 1, 2: 2}
    else:
        expected = {1: 1, n: 2, 2: n}
        expected.update({s: 3 for s in range(3, n)})   # 거리 8 동률 → 공동 3위
        assert ranks == expected


def test_standings_eliminated_in_reverse_order(seat_mode):
    mode, n = seat_mode
    game = new_game(mode)
    for seat_no in range(1, n):
        game.eliminate(seat_no, "surrender")

    ranks = {r["seat_no"]: r["rank"] for r in game.standings()}
    assert ranks == {s: n - s + 1 for s in range(1, n + 1)}


# ----- 직렬화 -----

def test_json_roundtrip_mid_game(seat_mode):
    mode, n = seat_mode
    game = new_game(mode, seed=7)
    step_one(game)
    game.place_wall(2, 3, 3, "horizontal")
    if n >= 3:
        game.eliminate(n, "time_forfeit")
    game.place_wall(game.current_seat_no, 3, 3, "vertical")  # 교차 → 카운터 1

    restored = GameState.from_dict(json.loads(json.dumps(game.to_dict())))

    assert restored.to_dict() == game.to_dict()
    assert len(restored.to_dict()["seats"]) == n


# ----- AI 자가대전 -----

@pytest.mark.parametrize("seed", [0, 1, 2])
def test_ai_self_play_terminates(seat_mode, seed):
    mode, n = seat_mode
    game = new_game(mode, seed=seed)
    ai = SimpleAI(rng=random.Random(seed))

    for _ in range(400):
        if game.is_finished:
            break
        seat_no = game.current_seat_no
        action = ai.get_move(game)
        if action.action_type == ActionType.MOVE:
            rejection = game.move(seat_no, action.row, action.col)
        else:
            rejection = game.place_wall(seat_no, action.row, action.col, action.orientation.value)
        assert rejection is None, f"AI action rejected: {rejection}"

    assert game.end_reason == EndReason.GOAL_REACHED


# ----- 하드코딩 회귀 방지 -----

def test_engine_has_no_two_player_literals():
    """엔진 소스에 2인 전제 식별자가 되살아나지 않는다"""
    engine_root = Path(__file__).resolve().parents[3] / "app" / "games" / "maze"
    pattern = re.compile(r"player[12]|PLAYER[12]|opponent_player|goal_row")
    sources = list(engine_root.rglob("*.py"))
    assert len(sources) >= 10, f"엔진 소스를 찾지 못했다: {engine_root}"  # 경로가 틀리면 공허하게 통과한다

    offenders = [
        f"{path.relative_to(engine_root)}:{lineno}: {line.strip()}"
        for path in sources
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]

    assert offenders == []
