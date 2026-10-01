"""
미로 엔진 테스트 픽스처
"""

import pytest

from app.games.maze.core.layouts import CORNER_SLOTS, LAYOUTS, Layout


# 테스트 전용 4인 배치. 인당 벽 수는 설계서에서 미정(§11 "—")이라 임의값이다
QUAD_LAYOUT = Layout(slots=CORNER_SLOTS, seats=4, walls_per_seat=5, shuffle=True)


@pytest.fixture(
    params=[("duel", 2), ("trio", 3), ("quad", 4)],
    ids=["duel-2", "trio-3", "quad-4"],
)
def seat_mode(request, monkeypatch) -> tuple[str, int]:
    """(mode, 좌석 수). quad 는 배치 테이블에 행을 **추가하는 것만으로** 주입한다.

    이 픽스처로 도는 테스트가 quad 에서 통과한다는 것이 M3 1단계 완료 판정이다 —
    "인원이 4명이 되면 무엇을 고쳐야 하는가?" → 테이블 행 추가뿐.
    """
    mode, seats = request.param
    if mode == "quad":
        monkeypatch.setitem(LAYOUTS, "quad", QUAD_LAYOUT)
    return mode, seats
