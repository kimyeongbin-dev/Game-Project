import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';
import '../services/ranking_service.dart';

class LeaderboardScreen extends StatefulWidget {
  const LeaderboardScreen({super.key});

  @override
  State<LeaderboardScreen> createState() => _LeaderboardScreenState();
}

class _LeaderboardScreenState extends State<LeaderboardScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  late RankingService _rankingService;

  LeaderboardResponse? _leaderboard;
  MyRankInfo? _myRank;
  List<DailyChampion> _recentChampions = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);

    // RankingService 초기화
    final authService = context.read<AuthService>();
    _rankingService = RankingService(
      baseUrl: authService.getServerUrl() + '/api/v1/ranking',
    );
    _rankingService.setAuthToken(authService.token);

    _loadData();
  }

  @override
  void dispose() {
    _tabController.dispose();
    _rankingService.dispose();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final results = await Future.wait([
        _rankingService.getLeaderboard(limit: 50),
        _rankingService.getMyRank(),
        _rankingService.getRecentChampions(days: 7),
      ]);

      setState(() {
        _leaderboard = results[0] as LeaderboardResponse?;
        _myRank = results[1] as MyRankInfo?;
        _recentChampions = results[2] as List<DailyChampion>;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = '데이터를 불러오지 못했습니다';
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('랭킹'),
        backgroundColor: colorScheme.inversePrimary,
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(text: '리더보드'),
            Tab(text: '챔피언 기록'),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadData,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(_error!),
                      const SizedBox(height: 16),
                      ElevatedButton(
                        onPressed: _loadData,
                        child: const Text('다시 시도'),
                      ),
                    ],
                  ),
                )
              : TabBarView(
                  controller: _tabController,
                  children: [
                    _buildLeaderboardTab(colorScheme),
                    _buildChampionsTab(colorScheme),
                  ],
                ),
    );
  }

  Widget _buildLeaderboardTab(ColorScheme colorScheme) {
    if (_leaderboard == null) {
      return const Center(child: Text('데이터 없음'));
    }

    return Column(
      children: [
        // 리셋 시간 표시
        if (_leaderboard!.timeRemaining != null)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            color: colorScheme.primaryContainer,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  Icons.timer,
                  size: 18,
                  color: colorScheme.onPrimaryContainer,
                ),
                const SizedBox(width: 8),
                Text(
                  '다음 리셋까지: ${_leaderboard!.timeRemaining}',
                  style: TextStyle(
                    color: colorScheme.onPrimaryContainer,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),

        // 내 순위 카드
        if (_myRank != null) _buildMyRankCard(_myRank!, colorScheme),

        // 전날 챔피언
        if (_leaderboard!.yesterdayChampion != null)
          _buildChampionBanner(_leaderboard!.yesterdayChampion!, colorScheme),

        // 리더보드 리스트
        Expanded(
          child: _leaderboard!.entries.isEmpty
              ? const Center(child: Text('아직 순위가 없습니다'))
              : ListView.builder(
                  padding: const EdgeInsets.all(8),
                  itemCount: _leaderboard!.entries.length,
                  itemBuilder: (context, index) {
                    return _buildLeaderboardEntry(
                      _leaderboard!.entries[index],
                      colorScheme,
                    );
                  },
                ),
        ),

        // 총 플레이어 수
        Padding(
          padding: const EdgeInsets.all(8),
          child: Text(
            '총 ${_leaderboard!.totalPlayers}명의 플레이어',
            style: TextStyle(color: colorScheme.onSurfaceVariant),
          ),
        ),
      ],
    );
  }

  Widget _buildMyRankCard(MyRankInfo myRank, ColorScheme colorScheme) {
    return Card(
      margin: const EdgeInsets.all(12),
      color: colorScheme.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            // 순위
            Container(
              width: 50,
              height: 50,
              decoration: BoxDecoration(
                color: colorScheme.primary,
                shape: BoxShape.circle,
              ),
              child: Center(
                child: Text(
                  '${myRank.rank}',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                    color: colorScheme.onPrimary,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 16),

            // 정보
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '내 순위',
                    style: TextStyle(
                      fontSize: 12,
                      color: colorScheme.onPrimaryContainer.withValues(alpha: 0.7),
                    ),
                  ),
                  Text(
                    myRank.nickname,
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: colorScheme.onPrimaryContainer,
                    ),
                  ),
                  Text(
                    '${myRank.score.toStringAsFixed(0)}점 · ${myRank.wins}승 ${myRank.losses}패',
                    style: TextStyle(
                      color: colorScheme.onPrimaryContainer.withValues(alpha: 0.8),
                    ),
                  ),
                ],
              ),
            ),

            // 퍼센타일
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: colorScheme.surface,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                myRank.percentile,
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  color: colorScheme.primary,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildChampionBanner(DailyChampion champion, ColorScheme colorScheme) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFFFFD700), Color(0xFFFFA500)],
        ),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          const Icon(Icons.emoji_events, color: Colors.white, size: 32),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '어제의 챔피언',
                  style: TextStyle(
                    color: Colors.white70,
                    fontSize: 12,
                  ),
                ),
                Text(
                  champion.nickname,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
          Text(
            '${champion.score.toStringAsFixed(0)}점',
            style: const TextStyle(
              color: Colors.white,
              fontSize: 16,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLeaderboardEntry(LeaderboardEntry entry, ColorScheme colorScheme) {
    final authService = context.read<AuthService>();
    final isMe = entry.nickname == authService.currentUser?.nickname;

    Color? rankColor;
    IconData? rankIcon;
    if (entry.rank == 1) {
      rankColor = const Color(0xFFFFD700);
      rankIcon = Icons.emoji_events;
    } else if (entry.rank == 2) {
      rankColor = const Color(0xFFC0C0C0);
      rankIcon = Icons.emoji_events;
    } else if (entry.rank == 3) {
      rankColor = const Color(0xFFCD7F32);
      rankIcon = Icons.emoji_events;
    }

    return Card(
      color: isMe ? colorScheme.primaryContainer.withValues(alpha: 0.3) : null,
      child: ListTile(
        leading: Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: rankColor ?? colorScheme.surfaceContainerHighest,
            shape: BoxShape.circle,
          ),
          child: Center(
            child: rankIcon != null
                ? Icon(rankIcon, size: 20, color: Colors.white)
                : Text(
                    '${entry.rank}',
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      color: colorScheme.onSurfaceVariant,
                    ),
                  ),
          ),
        ),
        title: Row(
          children: [
            Text(
              entry.nickname,
              style: TextStyle(
                fontWeight: isMe ? FontWeight.bold : FontWeight.normal,
              ),
            ),
            if (entry.isChampion) ...[
              const SizedBox(width: 8),
              const Icon(Icons.emoji_events, size: 16, color: Colors.amber),
            ],
            if (isMe) ...[
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: colorScheme.primary,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  'ME',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: colorScheme.onPrimary,
                  ),
                ),
              ),
            ],
          ],
        ),
        subtitle: Text(
          '${entry.wins}승 ${entry.losses}패 (${entry.winRate.toStringAsFixed(1)}%)',
        ),
        trailing: Text(
          '${entry.score.toStringAsFixed(0)}',
          style: const TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
    );
  }

  Widget _buildChampionsTab(ColorScheme colorScheme) {
    if (_recentChampions.isEmpty) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.emoji_events_outlined, size: 64, color: Colors.grey),
            SizedBox(height: 16),
            Text('아직 챔피언 기록이 없습니다'),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: _recentChampions.length,
      itemBuilder: (context, index) {
        final champion = _recentChampions[index];
        return Card(
          child: ListTile(
            leading: Container(
              width: 48,
              height: 48,
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  colors: [Color(0xFFFFD700), Color(0xFFFFA500)],
                ),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.emoji_events,
                color: Colors.white,
              ),
            ),
            title: Text(
              champion.nickname,
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            subtitle: Text(
              '${champion.date} · ${champion.wins}승 ${champion.losses}패',
            ),
            trailing: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  '${champion.score.toStringAsFixed(0)}점',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                if (champion.bestTurnCount != null)
                  Text(
                    '최단 ${champion.bestTurnCount}턴',
                    style: TextStyle(
                      fontSize: 12,
                      color: colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}
