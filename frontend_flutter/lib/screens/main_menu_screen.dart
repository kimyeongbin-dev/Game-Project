import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';
import 'quoridor_screen.dart';
import 'leaderboard_screen.dart';
import 'ranked_match_screen.dart';
import 'friend_match_screen.dart';

class MainMenuScreen extends StatefulWidget {
  const MainMenuScreen({super.key});

  @override
  State<MainMenuScreen> createState() => _MainMenuScreenState();
}

class _MainMenuScreenState extends State<MainMenuScreen> {
  @override
  void initState() {
    super.initState();
    // 유저 정보 새로고침
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<AuthService>().refreshUserInfo();
    });
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('로그아웃'),
        content: const Text('정말 로그아웃 하시겠습니까?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('로그아웃'),
          ),
        ],
      ),
    );

    if (confirmed == true && mounted) {
      await context.read<AuthService>().logout();
    }
  }

  @override
  Widget build(BuildContext context) {
    final authService = context.watch<AuthService>();
    final user = authService.currentUser;
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Game Hub'),
        backgroundColor: colorScheme.inversePrimary,
        actions: [
          // 랭킹 버튼
          IconButton(
            icon: const Icon(Icons.leaderboard),
            tooltip: '랭킹',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) => const LeaderboardScreen(),
                ),
              );
            },
          ),
          // 로그아웃 버튼
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: '로그아웃',
            onPressed: _logout,
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 유저 정보 카드
            if (user != null) _buildUserCard(user, colorScheme),
            const SizedBox(height: 32),

            // 게임 선택 헤더
            Text(
              '쿼리도 (Quoridor)',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '벽을 세워 상대를 막는 전략 보드게임',
              style: TextStyle(color: colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 24),

            // 게임 모드 카드들
            _buildGameModeCard(
              context,
              icon: Icons.smart_toy,
              title: 'AI 대전',
              description: 'AI와 연습 게임을 즐겨보세요',
              color: Colors.green,
              onTap: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => const QuoridorScreen(),
                  ),
                );
              },
            ),
            const SizedBox(height: 12),

            _buildGameModeCard(
              context,
              icon: Icons.people,
              title: '로컬 2인',
              description: '한 기기에서 친구와 함께',
              color: Colors.orange,
              onTap: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => const QuoridorScreen(
                      initialMode: 'local_2p',
                    ),
                  ),
                );
              },
            ),
            const SizedBox(height: 12),

            _buildGameModeCard(
              context,
              icon: Icons.emoji_events,
              title: '랭킹전',
              description: '랭킹 포인트를 걸고 온라인 대전',
              color: Colors.purple,
              badge: '온라인',
              onTap: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => const RankedMatchScreen(),
                  ),
                );
              },
            ),
            const SizedBox(height: 12),

            _buildGameModeCard(
              context,
              icon: Icons.group,
              title: '친구 대전',
              description: '방 코드로 친구와 온라인 대전',
              color: Colors.blue,
              badge: '온라인',
              onTap: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => const FriendMatchScreen(),
                  ),
                );
              },
            ),

            const SizedBox(height: 32),

            // 다른 게임 (준비 중)
            Text(
              '다른 게임',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 16),

            _buildGameModeCard(
              context,
              icon: Icons.circle_outlined,
              title: '오목 (Gomoku)',
              description: '준비 중...',
              color: Colors.grey,
              enabled: false,
              onTap: () {},
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildUserCard(UserInfo user, ColorScheme colorScheme) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            // 아바타
            CircleAvatar(
              radius: 30,
              backgroundColor: colorScheme.primaryContainer,
              child: Text(
                user.nickname.isNotEmpty ? user.nickname[0].toUpperCase() : '?',
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: colorScheme.onPrimaryContainer,
                ),
              ),
            ),
            const SizedBox(width: 16),

            // 유저 정보
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        user.nickname,
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      if (user.isChampion) ...[
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: Colors.amber,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.emoji_events, size: 14),
                              SizedBox(width: 4),
                              Text(
                                '챔피언',
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '점수: ${user.score.toStringAsFixed(0)} · '
                    '${user.wins}승 ${user.losses}패',
                    style: TextStyle(
                      color: colorScheme.onSurfaceVariant,
                    ),
                  ),
                  if (user.rank != null)
                    Text(
                      '순위: ${user.rank}위',
                      style: TextStyle(
                        color: colorScheme.primary,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                ],
              ),
            ),

            // 새로고침 버튼
            IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: () {
                context.read<AuthService>().refreshUserInfo();
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildGameModeCard(
    BuildContext context, {
    required IconData icon,
    required String title,
    required String description,
    required Color color,
    required VoidCallback onTap,
    String? badge,
    bool enabled = true,
  }) {
    final colorScheme = Theme.of(context).colorScheme;

    return Card(
      elevation: enabled ? 2 : 0,
      color: enabled ? null : colorScheme.surfaceContainerHighest,
      child: InkWell(
        onTap: enabled ? onTap : null,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              // 아이콘
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: enabled
                      ? color.withValues(alpha: 0.15)
                      : Colors.grey.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  icon,
                  size: 28,
                  color: enabled ? color : Colors.grey,
                ),
              ),
              const SizedBox(width: 16),

              // 텍스트
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          title,
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                            color: enabled ? null : Colors.grey,
                          ),
                        ),
                        if (badge != null) ...[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: color.withValues(alpha: 0.15),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              badge,
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.bold,
                                color: color,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      description,
                      style: TextStyle(
                        fontSize: 13,
                        color: enabled
                            ? colorScheme.onSurfaceVariant
                            : Colors.grey,
                      ),
                    ),
                  ],
                ),
              ),

              // 화살표
              if (enabled)
                Icon(
                  Icons.arrow_forward_ios,
                  size: 16,
                  color: colorScheme.onSurfaceVariant,
                ),
            ],
          ),
        ),
      ),
    );
  }
}
