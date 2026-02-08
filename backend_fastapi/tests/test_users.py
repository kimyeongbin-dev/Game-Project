"""
User Repository Tests
유저 등록, 로그인, 인증 테스트
"""

import pytest
from database.repository import UserRepository


class TestUserRepository:
    """유저 리포지토리 테스트"""

    async def test_create_user_success(self, user_repository: UserRepository):
        """유저 생성 성공 테스트"""
        user, error = await user_repository.create("testuser", "password123")

        assert user is not None
        assert error == ""
        assert user.nickname == "testuser"
        assert user.password_hash is not None
        assert user.session_token is not None
        assert user.score == 0
        assert user.wins == 0
        assert user.losses == 0
        assert user.is_online is True

    async def test_create_user_duplicate_nickname(self, user_repository: UserRepository):
        """닉네임 중복 테스트"""
        # 첫 번째 유저 생성
        user1, _ = await user_repository.create("duplicate", "pass1234")
        assert user1 is not None

        # 같은 닉네임으로 두 번째 유저 생성 시도
        user2, error = await user_repository.create("duplicate", "pass5678")
        assert user2 is None
        assert "이미 사용 중인 닉네임" in error

    async def test_create_user_invalid_nickname_short(self, user_repository: UserRepository):
        """짧은 닉네임 테스트"""
        user, error = await user_repository.create("a", "password123")
        assert user is None
        assert "2자 이상" in error

    async def test_create_user_invalid_nickname_long(self, user_repository: UserRepository):
        """긴 닉네임 테스트"""
        user, error = await user_repository.create("a" * 15, "password123")
        assert user is None
        assert "12자 이하" in error

    async def test_create_user_invalid_nickname_special_chars(self, user_repository: UserRepository):
        """특수문자 닉네임 테스트"""
        user, error = await user_repository.create("test@user", "password123")
        assert user is None
        assert "영문, 숫자, 한글만" in error

    async def test_create_user_korean_nickname(self, user_repository: UserRepository):
        """한글 닉네임 테스트"""
        user, error = await user_repository.create("테스트유저", "password123")
        assert user is not None
        assert user.nickname == "테스트유저"

    async def test_create_user_short_password(self, user_repository: UserRepository):
        """짧은 비밀번호 테스트"""
        user, error = await user_repository.create("testuser", "123")
        assert user is None
        assert "4자 이상" in error

    async def test_login_success(self, user_repository: UserRepository):
        """로그인 성공 테스트"""
        # 유저 생성
        await user_repository.create("logintest", "mypassword")

        # 로그인
        user, error = await user_repository.login("logintest", "mypassword")
        assert user is not None
        assert error == ""
        assert user.nickname == "logintest"
        assert user.is_online is True

    async def test_login_wrong_password(self, user_repository: UserRepository):
        """잘못된 비밀번호 테스트"""
        # 유저 생성
        await user_repository.create("wrongpass", "correctpassword")

        # 잘못된 비밀번호로 로그인
        user, error = await user_repository.login("wrongpass", "wrongpassword")
        assert user is None
        assert "올바르지 않습니다" in error

    async def test_login_nonexistent_user(self, user_repository: UserRepository):
        """존재하지 않는 유저 로그인 테스트"""
        user, error = await user_repository.login("nonexistent", "password123")
        assert user is None
        assert "올바르지 않습니다" in error

    async def test_login_generates_new_token(self, user_repository: UserRepository):
        """로그인 시 새 토큰 발급 테스트"""
        # 유저 생성
        user1, _ = await user_repository.create("tokentest", "password123")
        old_token = user1.session_token

        # 로그인
        user2, _ = await user_repository.login("tokentest", "password123")
        new_token = user2.session_token

        assert old_token != new_token

    async def test_get_by_token(self, user_repository: UserRepository):
        """토큰으로 유저 조회 테스트"""
        # 유저 생성
        created_user, _ = await user_repository.create("tokenuser", "password123")

        # 토큰으로 조회
        found_user = await user_repository.get_by_token(created_user.session_token)
        assert found_user is not None
        assert found_user.id == created_user.id

    async def test_get_by_invalid_token(self, user_repository: UserRepository):
        """잘못된 토큰 조회 테스트"""
        user = await user_repository.get_by_token("invalid_token_12345")
        assert user is None

    async def test_update_score_win(self, user_repository: UserRepository):
        """승리 시 점수 업데이트 테스트"""
        # 유저 생성
        user, _ = await user_repository.create("scoretest", "password123")

        # 점수 업데이트 (승리)
        updated = await user_repository.update_score(
            user_id=user.id,
            score_change=3.5,  # 기본 3 + 턴 보너스 0.5
            is_win=True,
            turn_count=20
        )

        assert updated is not None
        assert updated.score == 3.5
        assert updated.wins == 1
        assert updated.losses == 0
        assert updated.best_turn_count == 20

    async def test_update_score_loss(self, user_repository: UserRepository):
        """패배 시 점수 업데이트 테스트"""
        # 유저 생성
        user, _ = await user_repository.create("losstest", "password123")

        # 점수 업데이트 (패배)
        updated = await user_repository.update_score(
            user_id=user.id,
            score_change=-1,
            is_win=False
        )

        assert updated is not None
        assert updated.score == 0  # 최소 0점
        assert updated.wins == 0
        assert updated.losses == 1

    async def test_update_best_turn_count(self, user_repository: UserRepository):
        """최단 턴 업데이트 테스트"""
        # 유저 생성
        user, _ = await user_repository.create("turntest", "password123")

        # 첫 번째 승리 (30턴)
        await user_repository.update_score(user.id, 3, True, 30)
        user = await user_repository.get_by_id(user.id)
        assert user.best_turn_count == 30

        # 두 번째 승리 (20턴 - 더 빠름)
        await user_repository.update_score(user.id, 3, True, 20)
        user = await user_repository.get_by_id(user.id)
        assert user.best_turn_count == 20

        # 세 번째 승리 (25턴 - 더 느림, 업데이트 안됨)
        await user_repository.update_score(user.id, 3, True, 25)
        user = await user_repository.get_by_id(user.id)
        assert user.best_turn_count == 20

    async def test_logout(self, user_repository: UserRepository):
        """로그아웃 테스트"""
        # 유저 생성
        user, _ = await user_repository.create("logouttest", "password123")
        assert user.is_online is True

        # 로그아웃
        success = await user_repository.logout(user.id)
        assert success is True

        # 상태 확인
        user = await user_repository.get_by_id(user.id)
        assert user.is_online is False

    async def test_reset_stats(self, user_repository: UserRepository):
        """통계 리셋 테스트"""
        # 유저 생성 및 점수 쌓기
        user, _ = await user_repository.create("resettest", "password123")
        await user_repository.update_score(user.id, 10, True, 15)
        await user_repository.update_score(user.id, 3, True, 20)

        user = await user_repository.get_by_id(user.id)
        assert user.score == 13
        assert user.wins == 2

        # 리셋
        success = await user_repository.reset_stats(user.id)
        assert success is True

        user = await user_repository.get_by_id(user.id)
        assert user.score == 0
        assert user.wins == 0
        assert user.losses == 0
        assert user.best_turn_count is None
