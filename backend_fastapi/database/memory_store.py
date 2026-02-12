"""
In-Memory Store for Development/Testing
DB 없이 테스트용 인메모리 저장소
"""

import secrets
import bcrypt
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List
from dataclasses import dataclass, field


# 세션 만료 시간 (시간)
SESSION_EXPIRE_HOURS = 24


@dataclass
class MemoryUser:
    """인메모리 유저 객체"""
    id: int
    nickname: str
    password_hash: str
    session_token: str
    token_expires_at: datetime
    score: float = 0.0
    wins: int = 0
    losses: int = 0
    best_turn_count: Optional[int] = None
    is_online: bool = False
    current_game_id: Optional[str] = None
    last_active_at: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def is_token_valid(self) -> bool:
        if self.token_expires_at is None:
            return True
        return datetime.utcnow() < self.token_expires_at


@dataclass
class MemoryDailyChampion:
    """인메모리 일일 챔피언"""
    id: int
    nickname: str
    score: float
    wins: int
    losses: int
    best_turn_count: Optional[int]
    champion_date: date
    reset_at: datetime


class InMemoryUserStore:
    """인메모리 유저 저장소 (싱글톤)"""

    def __init__(self):
        self._users: Dict[int, MemoryUser] = {}
        self._next_id = 1
        self._champions: List[MemoryDailyChampion] = []
        self._initialized = False

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def _verify_password(self, password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

    def _generate_token(self) -> tuple[str, datetime]:
        token = secrets.token_hex(32)
        expires_at = datetime.utcnow() + timedelta(hours=SESSION_EXPIRE_HOURS)
        return token, expires_at

    def initialize_test_users(self):
        """테스트 유저 초기화"""
        if self._initialized:
            return

        # 테스트 유저 목록: (닉네임, 비밀번호, 점수, 승, 패, 최단턴)
        test_users = [
            # 기본 테스트 유저
            ("tester1", "tester1", 0.0, 0, 0, None),
            ("tester2", "tester2", 0.0, 0, 0, None),

            # 전날 챔피언
            ("champion", "champion", 100.0, 10, 2, 15),

            # 리더보드 테스트용 (다양한 순위)
            ("pro1", "pro1", 85.5, 8, 1, 18),        # 2위
            ("pro2", "pro2", 72.0, 7, 2, 20),        # 3위
            ("mid1", "mid1", 45.0, 5, 4, 25),        # 중위권
            ("mid2", "mid2", 30.0, 3, 3, 30),        # 중위권
            ("newbie", "newbie", 5.0, 1, 5, None),   # 초보 (패배 다수)

            # 랭킹전 테스트용
            ("ranker1", "ranker1", 50.0, 5, 2, 22),
            ("ranker2", "ranker2", 48.0, 5, 3, 24),

            # 친구대전 테스트용
            ("friend1", "friend1", 20.0, 2, 1, 28),
            ("friend2", "friend2", 15.0, 2, 2, 32),

            # AI 대전 테스트용
            ("aiPlayer", "aiPlayer", 35.0, 4, 2, 26),

            # 엣지 케이스 테스트
            ("한글유저", "hangul123", 10.0, 1, 1, None),  # 한글 닉네임
            ("User123", "User123", 25.0, 3, 2, 35),       # 영문+숫자
        ]

        for nickname, password, score, wins, losses, best_turn in test_users:
            token, expires_at = self._generate_token()
            user = MemoryUser(
                id=self._next_id,
                nickname=nickname,
                password_hash=self._hash_password(password),
                session_token=token,
                token_expires_at=expires_at,
                score=score,
                wins=wins,
                losses=losses,
                best_turn_count=best_turn,
            )
            self._users[self._next_id] = user
            self._next_id += 1

        # champion을 어제의 챔피언으로 등록
        yesterday = date.today() - timedelta(days=1)
        self._champions.append(MemoryDailyChampion(
            id=1,
            nickname="champion",
            score=100.0,
            wins=10,
            losses=2,
            best_turn_count=15,
            champion_date=yesterday,
            reset_at=datetime.utcnow()
        ))

        self._initialized = True
        print(f"[InMemoryStore] {len(test_users)} test users initialized")

    def create_user(self, nickname: str, password: str) -> tuple[Optional[MemoryUser], str]:
        """유저 생성"""
        # 중복 체크
        for user in self._users.values():
            if user.nickname == nickname:
                return None, "이미 사용 중인 닉네임입니다"

        token, expires_at = self._generate_token()
        user = MemoryUser(
            id=self._next_id,
            nickname=nickname,
            password_hash=self._hash_password(password),
            session_token=token,
            token_expires_at=expires_at,
            is_online=True
        )
        self._users[self._next_id] = user
        self._next_id += 1
        return user, ""

    def login(self, nickname: str, password: str) -> tuple[Optional[MemoryUser], str]:
        """로그인"""
        for user in self._users.values():
            if user.nickname == nickname:
                if self._verify_password(password, user.password_hash):
                    # 새 토큰 발급
                    token, expires_at = self._generate_token()
                    user.session_token = token
                    user.token_expires_at = expires_at
                    user.is_online = True
                    user.last_active_at = datetime.utcnow()
                    return user, ""
                else:
                    return None, "닉네임 또는 비밀번호가 올바르지 않습니다"
        return None, "닉네임 또는 비밀번호가 올바르지 않습니다"

    def get_by_token(self, token: str) -> Optional[MemoryUser]:
        """토큰으로 유저 조회"""
        for user in self._users.values():
            if user.session_token == token and user.is_token_valid():
                return user
        return None

    def get_by_id(self, user_id: int) -> Optional[MemoryUser]:
        """ID로 유저 조회"""
        return self._users.get(user_id)

    def get_by_nickname(self, nickname: str) -> Optional[MemoryUser]:
        """닉네임으로 유저 조회"""
        for user in self._users.values():
            if user.nickname == nickname:
                return user
        return None

    def get_leaderboard(self, limit: int = 20) -> List[MemoryUser]:
        """리더보드 조회"""
        sorted_users = sorted(
            self._users.values(),
            key=lambda u: (-u.score, -u.wins, u.best_turn_count or 999)
        )
        return sorted_users[:limit]

    def get_total_users(self) -> int:
        """총 유저 수"""
        return len(self._users)

    def get_user_rank(self, user_id: int) -> int:
        """유저 순위 조회"""
        sorted_users = sorted(
            self._users.values(),
            key=lambda u: (-u.score, -u.wins, u.best_turn_count or 999)
        )
        for idx, user in enumerate(sorted_users, 1):
            if user.id == user_id:
                return idx
        return 0

    def get_yesterday_champion(self) -> Optional[MemoryDailyChampion]:
        """어제의 챔피언 조회"""
        yesterday = date.today() - timedelta(days=1)
        for champ in self._champions:
            if champ.champion_date == yesterday:
                return champ
        return None

    def get_recent_champions(self, days: int = 7) -> List[MemoryDailyChampion]:
        """최근 N일 챔피언 목록"""
        return sorted(self._champions, key=lambda c: c.champion_date, reverse=True)[:days]

    def update_heartbeat(self, user_id: int) -> bool:
        """하트비트 업데이트"""
        user = self._users.get(user_id)
        if user:
            user.is_online = True
            user.last_active_at = datetime.utcnow()
            user.token_expires_at = datetime.utcnow() + timedelta(hours=SESSION_EXPIRE_HOURS)
            return True
        return False

    def logout(self, user_id: int) -> bool:
        """로그아웃"""
        user = self._users.get(user_id)
        if user:
            user.is_online = False
            user.current_game_id = None
            return True
        return False

    def update_score(self, user_id: int, score_change: float, is_win: bool, turn_count: Optional[int] = None) -> Optional[MemoryUser]:
        """점수 업데이트"""
        user = self._users.get(user_id)
        if not user:
            return None

        user.score = max(0, user.score + score_change)
        if is_win:
            user.wins += 1
            if turn_count and (user.best_turn_count is None or turn_count < user.best_turn_count):
                user.best_turn_count = turn_count
        else:
            user.losses += 1
        return user


# 싱글톤 인스턴스
memory_store = InMemoryUserStore()
