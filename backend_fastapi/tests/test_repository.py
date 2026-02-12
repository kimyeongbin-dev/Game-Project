"""
Repository Tests
데이터베이스 Repository CRUD 테스트

Note: PostgreSQL DB가 필요합니다. DB 없으면 테스트가 스킵됩니다.
"""

import pytest
from datetime import date, timedelta
import uuid


# ==============================================
# GameSessionRepository 테스트
# ==============================================

@pytest.mark.requires_db
class TestGameSessionCreate:
    """게임 세션 생성 테스트"""

    @pytest.mark.asyncio
    async def test_create_game_session(self, repository, sample_game_state):
        """게임 세션 생성"""
        game_id = str(uuid.uuid4())
        game = await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        assert game is not None
        assert game.game_id == game_id
        assert game.player1_name == "Player 1"
        assert game.player2_name == "AI"
        assert game.game_mode.value == "vs_ai"
        assert game.ai_difficulty == "normal"
        assert game.status.value == "in_progress"
        assert game.current_turn == 1
        assert game.turn_count == 0

    @pytest.mark.asyncio
    async def test_create_friend_match_game(self, repository, sample_game_state):
        """친구대전 게임 생성"""
        game_id = str(uuid.uuid4())
        game = await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="Player 2",
            game_mode="friend_match",
            ai_difficulty=None,
            game_state=sample_game_state
        )

        assert game is not None
        assert game.game_mode.value == "friend_match"
        assert game.ai_difficulty is None

    @pytest.mark.asyncio
    async def test_create_ranked_game(self, repository, sample_game_state):
        """랭킹전 게임 생성"""
        game_id = str(uuid.uuid4())
        game = await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="Player 2",
            game_mode="ranked",
            ai_difficulty=None,
            game_state=sample_game_state,
            is_ranked=True,
            player1_user_id=1
        )

        assert game is not None
        assert game.game_mode.value == "ranked"
        assert game.is_ranked is True
        assert game.player1_user_id == 1


@pytest.mark.requires_db
class TestGameSessionRead:
    """게임 세션 조회 테스트"""

    @pytest.mark.asyncio
    async def test_get_by_id(self, repository, sample_game_state):
        """ID로 조회"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        game = await repository.get_by_id(game_id)
        assert game is not None
        assert game.game_id == game_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_game(self, repository):
        """존재하지 않는 게임 조회"""
        game = await repository.get_by_id("nonexistent-id")
        assert game is None

    @pytest.mark.asyncio
    async def test_get_active_sessions(self, repository, sample_game_state):
        """진행 중인 세션 목록"""
        # 게임 3개 생성
        for i in range(3):
            await repository.create(
                game_id=str(uuid.uuid4()),
                player1_name=f"Player {i}",
                player2_name="AI",
                game_mode="vs_ai",
                ai_difficulty="normal",
                game_state=sample_game_state
            )

        sessions = await repository.get_active_sessions(limit=10)
        assert len(sessions) == 3
        # 최신 순서로 정렬 확인
        for i in range(len(sessions) - 1):
            assert sessions[i].updated_at >= sessions[i + 1].updated_at


@pytest.mark.requires_db
class TestGameSessionUpdate:
    """게임 세션 업데이트 테스트"""

    @pytest.mark.asyncio
    async def test_update_game_state(self, repository, sample_game_state):
        """게임 상태 업데이트"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 게임 상태 업데이트
        new_state = sample_game_state.copy()
        new_state["turn_count"] = 5
        new_state["current_turn"] = 2

        updated = await repository.update_game_state(
            game_id=game_id,
            game_state=new_state
        )

        assert updated is not None
        assert updated.turn_count == 5
        assert updated.current_turn == 2

    @pytest.mark.asyncio
    async def test_update_with_winner(self, repository, sample_game_state):
        """승자 정보 업데이트"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        updated = await repository.update_game_state(
            game_id=game_id,
            game_state=sample_game_state,
            status="player1_win",
            winner=1
        )

        assert updated is not None
        assert updated.status.value == "player1_win"
        assert updated.winner == 1


@pytest.mark.requires_db
class TestGameSessionDelete:
    """게임 세션 삭제 테스트"""

    @pytest.mark.asyncio
    async def test_abandon_game(self, repository, sample_game_state):
        """게임 포기 (ABANDONED 상태)"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        result = await repository.abandon_game(game_id)
        assert result is True

        game = await repository.get_by_id(game_id)
        assert game.status.value == "abandoned"

    @pytest.mark.asyncio
    async def test_hard_delete(self, repository, sample_game_state):
        """완전 삭제 (is_deleted=True)"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        result = await repository.hard_delete(game_id)
        assert result is True

        # 삭제된 게임은 조회 안됨
        game = await repository.get_by_id(game_id)
        assert game is None


@pytest.mark.requires_db
class TestGameMoves:
    """게임 수 기록 테스트 (리플레이 시스템)"""

    @pytest.mark.asyncio
    async def test_add_move(self, repository, sample_game_state):
        """수 추가"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        move = await repository.add_move(
            game_id=game_id,
            step_no=0,
            player=1,
            action_type="move",
            row=7,
            col=4,
            orientation=None,
            game_state_snapshot=sample_game_state
        )

        assert move is not None
        assert move.step_no == 0
        assert move.player == 1
        assert move.action_type.value == "move"
        assert move.row == 7
        assert move.col == 4

    @pytest.mark.asyncio
    async def test_add_initial_state(self, repository, sample_game_state):
        """초기 상태 저장 (step -1)"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 초기 상태는 step -1
        move = await repository.add_move(
            game_id=game_id,
            step_no=-1,
            player=0,
            action_type="move",
            row=0,
            col=0,
            orientation=None,
            game_state_snapshot=sample_game_state
        )

        assert move is not None
        assert move.step_no == -1

    @pytest.mark.asyncio
    async def test_get_moves(self, repository, sample_game_state):
        """수 목록 조회"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 3개 수 추가
        for i in range(3):
            await repository.add_move(
                game_id=game_id,
                step_no=i,
                player=(i % 2) + 1,
                action_type="move",
                row=7 - i,
                col=4,
                orientation=None,
                game_state_snapshot=sample_game_state
            )

        moves = await repository.get_moves(game_id)
        assert len(moves) == 3
        # step_no 순서로 정렬 확인
        assert moves[0].step_no == 0
        assert moves[1].step_no == 1
        assert moves[2].step_no == 2

    @pytest.mark.asyncio
    async def test_get_total_moves(self, repository, sample_game_state):
        """총 수 개수 (step >= 0만 카운트)"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 초기 상태 (step -1)
        await repository.add_move(
            game_id=game_id,
            step_no=-1,
            player=0,
            action_type="move",
            row=0, col=0, orientation=None,
            game_state_snapshot=sample_game_state
        )

        # 3개 수 추가
        for i in range(3):
            await repository.add_move(
                game_id=game_id,
                step_no=i,
                player=(i % 2) + 1,
                action_type="move",
                row=7 - i, col=4, orientation=None,
                game_state_snapshot=sample_game_state
            )

        total = await repository.get_total_moves(game_id)
        assert total == 3  # step -1 제외

    @pytest.mark.asyncio
    async def test_get_state_at_step(self, repository, sample_game_state):
        """특정 스텝 상태 조회"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 상태 저장
        state_at_step1 = sample_game_state.copy()
        state_at_step1["turn_count"] = 1
        await repository.add_move(
            game_id=game_id,
            step_no=0,
            player=1,
            action_type="move",
            row=7, col=4, orientation=None,
            game_state_snapshot=state_at_step1
        )

        # 스텝 0 상태 조회
        state = await repository.get_state_at_step(game_id, 0)
        assert state is not None
        assert state["turn_count"] == 1

    @pytest.mark.asyncio
    async def test_wall_move_record(self, repository, sample_game_state):
        """벽 설치 기록"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        move = await repository.add_move(
            game_id=game_id,
            step_no=0,
            player=1,
            action_type="wall",
            row=4,
            col=4,
            orientation="horizontal",
            game_state_snapshot=sample_game_state
        )

        assert move.action_type.value == "wall"
        assert move.orientation == "horizontal"

    @pytest.mark.asyncio
    async def test_delete_moves_after(self, repository, sample_game_state):
        """특정 스텝 이후 수 삭제"""
        game_id = str(uuid.uuid4())
        await repository.create(
            game_id=game_id,
            player1_name="Player 1",
            player2_name="AI",
            game_mode="vs_ai",
            ai_difficulty="normal",
            game_state=sample_game_state
        )

        # 5개 수 추가
        for i in range(5):
            await repository.add_move(
                game_id=game_id,
                step_no=i,
                player=(i % 2) + 1,
                action_type="move",
                row=7 - i, col=4, orientation=None,
                game_state_snapshot=sample_game_state
            )

        # step 2 이후 삭제 (step 3, 4 삭제)
        deleted_count = await repository.delete_moves_after(game_id, 2)
        assert deleted_count == 2

        moves = await repository.get_moves(game_id)
        assert len(moves) == 3


# ==============================================
# UserRepository 테스트
# ==============================================

@pytest.mark.requires_db
class TestUserCreate:
    """유저 생성 테스트"""

    @pytest.mark.asyncio
    async def test_create_user_success(self, user_repository):
        """유저 생성 성공"""
        user, error = await user_repository.create("TestUser", "password123")

        assert user is not None
        assert error == ""
        assert user.nickname == "TestUser"
        assert user.session_token is not None
        assert len(user.session_token) == 64
        assert user.score == 0
        assert user.wins == 0
        assert user.losses == 0
        assert user.is_online is True

    @pytest.mark.asyncio
    async def test_create_user_duplicate_nickname(self, user_repository):
        """닉네임 중복"""
        await user_repository.create("DuplicateUser", "password123")
        user, error = await user_repository.create("DuplicateUser", "password456")

        assert user is None
        assert "이미 사용 중인 닉네임" in error

    @pytest.mark.asyncio
    async def test_create_user_short_nickname(self, user_repository):
        """너무 짧은 닉네임"""
        user, error = await user_repository.create("A", "password123")

        assert user is None
        assert "2자 이상" in error

    @pytest.mark.asyncio
    async def test_create_user_long_nickname(self, user_repository):
        """너무 긴 닉네임"""
        user, error = await user_repository.create("VeryLongNickname123", "password123")

        assert user is None
        assert "12자 이하" in error

    @pytest.mark.asyncio
    async def test_create_user_special_chars(self, user_repository):
        """특수문자 닉네임"""
        user, error = await user_repository.create("Test@User!", "password123")

        assert user is None
        assert "영문, 숫자, 한글" in error

    @pytest.mark.asyncio
    async def test_create_user_korean_nickname(self, user_repository):
        """한글 닉네임"""
        user, error = await user_repository.create("테스트유저", "password123")

        assert user is not None
        assert user.nickname == "테스트유저"

    @pytest.mark.asyncio
    async def test_create_user_short_password(self, user_repository):
        """너무 짧은 비밀번호"""
        user, error = await user_repository.create("TestUser", "123")

        assert user is None
        assert "4자 이상" in error


@pytest.mark.requires_db
class TestUserLogin:
    """유저 로그인 테스트"""

    @pytest.mark.asyncio
    async def test_login_success(self, user_repository):
        """로그인 성공"""
        await user_repository.create("LoginUser", "password123")
        user, error = await user_repository.login("LoginUser", "password123")

        assert user is not None
        assert error == ""
        assert user.is_online is True

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, user_repository):
        """잘못된 비밀번호"""
        await user_repository.create("WrongPwUser", "password123")
        user, error = await user_repository.login("WrongPwUser", "wrongpassword")

        assert user is None
        assert "올바르지 않습니다" in error

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, user_repository):
        """존재하지 않는 유저"""
        user, error = await user_repository.login("NonexistentUser", "password123")

        assert user is None
        assert "올바르지 않습니다" in error

    @pytest.mark.asyncio
    async def test_login_generates_new_token(self, user_repository):
        """로그인 시 새 토큰 발급"""
        created_user, _ = await user_repository.create("TokenUser", "password123")
        old_token = created_user.session_token

        logged_in_user, _ = await user_repository.login("TokenUser", "password123")

        assert logged_in_user.session_token != old_token


@pytest.mark.requires_db
class TestUserToken:
    """토큰 관련 테스트"""

    @pytest.mark.asyncio
    async def test_get_by_token(self, user_repository):
        """토큰으로 유저 조회"""
        created_user, _ = await user_repository.create("TokenLookup", "password123")

        found_user = await user_repository.get_by_token(created_user.session_token)

        assert found_user is not None
        assert found_user.id == created_user.id

    @pytest.mark.asyncio
    async def test_get_by_invalid_token(self, user_repository):
        """유효하지 않은 토큰"""
        user = await user_repository.get_by_token("invalid-token")

        assert user is None


@pytest.mark.requires_db
class TestUserScore:
    """점수 업데이트 테스트"""

    @pytest.mark.asyncio
    async def test_update_score_win(self, user_repository):
        """승리 시 점수 업데이트"""
        user, _ = await user_repository.create("WinUser", "password123")

        updated = await user_repository.update_score(
            user_id=user.id,
            score_change=5.0,
            is_win=True,
            turn_count=20
        )

        assert updated is not None
        assert updated.score == 5.0
        assert updated.wins == 1
        assert updated.best_turn_count == 20

    @pytest.mark.asyncio
    async def test_update_score_loss(self, user_repository):
        """패배 시 점수 업데이트"""
        user, _ = await user_repository.create("LoseUser", "password123")
        # 먼저 점수를 올려놓음
        await user_repository.update_score(user.id, 10.0, True)

        updated = await user_repository.update_score(
            user_id=user.id,
            score_change=-1.0,
            is_win=False
        )

        assert updated is not None
        assert updated.score == 9.0
        assert updated.losses == 1

    @pytest.mark.asyncio
    async def test_update_best_turn_count(self, user_repository):
        """최단 턴 업데이트"""
        user, _ = await user_repository.create("TurnUser", "password123")

        # 첫 승리 - 30턴
        await user_repository.update_score(user.id, 3.0, True, turn_count=30)
        user = await user_repository.get_by_id(user.id)
        assert user.best_turn_count == 30

        # 두번째 승리 - 20턴 (더 빠름)
        await user_repository.update_score(user.id, 3.0, True, turn_count=20)
        user = await user_repository.get_by_id(user.id)
        assert user.best_turn_count == 20

        # 세번째 승리 - 25턴 (더 느림, 갱신 안됨)
        await user_repository.update_score(user.id, 3.0, True, turn_count=25)
        user = await user_repository.get_by_id(user.id)
        assert user.best_turn_count == 20


@pytest.mark.requires_db
class TestUserLogout:
    """로그아웃 테스트"""

    @pytest.mark.asyncio
    async def test_logout(self, user_repository):
        """로그아웃"""
        user, _ = await user_repository.create("LogoutUser", "password123")

        result = await user_repository.logout(user.id)

        assert result is True
        user = await user_repository.get_by_id(user.id)
        assert user.is_online is False

    @pytest.mark.asyncio
    async def test_reset_stats(self, user_repository):
        """통계 리셋"""
        user, _ = await user_repository.create("ResetUser", "password123")
        await user_repository.update_score(user.id, 10.0, True, turn_count=20)

        result = await user_repository.reset_stats(user.id)

        assert result is True
        user = await user_repository.get_by_id(user.id)
        assert user.score == 0
        assert user.wins == 0
        assert user.losses == 0
        assert user.best_turn_count is None


# ==============================================
# RankingRepository 테스트
# ==============================================

@pytest.mark.requires_db
class TestRankingLeaderboard:
    """리더보드 테스트"""

    @pytest.mark.asyncio
    async def test_get_leaderboard_empty(self, ranking_repository):
        """빈 리더보드"""
        leaderboard = await ranking_repository.get_leaderboard()
        assert leaderboard == []

    @pytest.mark.asyncio
    async def test_get_leaderboard_sorted(self, user_repository, ranking_repository):
        """점수 기준 정렬"""
        # 유저 3명 생성 (다른 점수)
        user1, _ = await user_repository.create("Rank1", "password")
        user2, _ = await user_repository.create("Rank2", "password")
        user3, _ = await user_repository.create("Rank3", "password")

        await user_repository.update_score(user1.id, 10.0, True)
        await user_repository.update_score(user2.id, 30.0, True)
        await user_repository.update_score(user3.id, 20.0, True)

        leaderboard = await ranking_repository.get_leaderboard()

        assert len(leaderboard) == 3
        assert leaderboard[0].nickname == "Rank2"  # 30점
        assert leaderboard[1].nickname == "Rank3"  # 20점
        assert leaderboard[2].nickname == "Rank1"  # 10점

    @pytest.mark.asyncio
    async def test_get_user_rank(self, user_repository, ranking_repository):
        """유저 순위 조회"""
        user1, _ = await user_repository.create("RankUser1", "password")
        user2, _ = await user_repository.create("RankUser2", "password")

        await user_repository.update_score(user1.id, 100.0, True)
        await user_repository.update_score(user2.id, 50.0, True)

        rank1 = await ranking_repository.get_user_rank(user1.id)
        rank2 = await ranking_repository.get_user_rank(user2.id)

        assert rank1 == 1
        assert rank2 == 2


@pytest.mark.requires_db
class TestDailyChampion:
    """일일 챔피언 테스트"""

    @pytest.mark.asyncio
    async def test_save_daily_champion(self, ranking_repository):
        """일일 챔피언 저장"""
        today = date.today()
        champion = await ranking_repository.save_daily_champion(
            nickname="ChampionUser",
            score=100.0,
            wins=10,
            losses=2,
            best_turn_count=15,
            champion_date=today
        )

        assert champion is not None
        assert champion.nickname == "ChampionUser"
        assert champion.score == 100.0
        assert champion.champion_date == today

    @pytest.mark.asyncio
    async def test_get_champion_by_date(self, ranking_repository):
        """날짜별 챔피언 조회"""
        today = date.today()
        await ranking_repository.save_daily_champion(
            nickname="DateChampion",
            score=50.0,
            wins=5,
            losses=1,
            best_turn_count=20,
            champion_date=today
        )

        champion = await ranking_repository.get_champion_by_date(today)

        assert champion is not None
        assert champion.nickname == "DateChampion"

    @pytest.mark.asyncio
    async def test_get_recent_champions(self, ranking_repository):
        """최근 챔피언 목록"""
        today = date.today()

        # 3일치 챔피언 저장
        for i in range(3):
            await ranking_repository.save_daily_champion(
                nickname=f"Champion{i}",
                score=float(100 - i * 10),
                wins=10 - i,
                losses=i,
                best_turn_count=15 + i,
                champion_date=today - timedelta(days=i)
            )

        champions = await ranking_repository.get_recent_champions(days=7)

        assert len(champions) == 3
        # 날짜 내림차순
        assert champions[0].champion_date == today
