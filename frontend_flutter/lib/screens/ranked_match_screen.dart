import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';
import '../services/websocket_service.dart';
import 'online_game_screen.dart';

class RankedMatchScreen extends StatefulWidget {
  const RankedMatchScreen({super.key});

  @override
  State<RankedMatchScreen> createState() => _RankedMatchScreenState();
}

class _RankedMatchScreenState extends State<RankedMatchScreen>
    with TickerProviderStateMixin {
  late WebSocketService _wsService;
  late AnimationController _pulseController;
  Timer? _queueTimer;
  int _queueSeconds = 0;
  bool _isConnecting = false;
  bool _navigatingToGame = false;  // 게임 화면으로 이동 중인지

  @override
  void initState() {
    super.initState();
    _wsService = WebSocketService();

    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat();

    _setupWebSocket();
  }

  @override
  void dispose() {
    debugPrint('[RankedMatch] dispose() called, _navigatingToGame: $_navigatingToGame');
    _queueTimer?.cancel();
    _pulseController.dispose();
    // 게임 화면으로 이동 중이면 WebSocket 유지
    if (!_navigatingToGame) {
      debugPrint('[RankedMatch] Disposing WebSocket');
      _wsService.dispose();
    } else {
      debugPrint('[RankedMatch] Keeping WebSocket alive for game');
    }
    super.dispose();
  }

  Future<void> _setupWebSocket() async {
    final authService = context.read<AuthService>();
    final serverUrl = authService.getServerUrl();
    final token = authService.token;

    if (token == null) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('로그인이 필요합니다')),
        );
        Navigator.pop(context);
      }
      return;
    }

    _wsService.onMatchFound = _onMatchFound;
    _wsService.onError = _onError;
    _wsService.addListener(_onStateChanged);

    setState(() => _isConnecting = true);

    final connected = await _wsService.connect(serverUrl, token);

    if (mounted) {
      setState(() => _isConnecting = false);

      if (!connected) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('서버 연결 실패: ${_wsService.lastError}')),
        );
      }
    }
  }

  void _onStateChanged() {
    if (mounted) setState(() {});
  }

  void _onMatchFound(MatchInfo match) {
    _queueTimer?.cancel();
    debugPrint('[RankedMatch] _onMatchFound called, _navigatingToGame was: $_navigatingToGame');

    // 이미 이동 중이면 무시 (중복 호출 방지)
    if (_navigatingToGame) {
      debugPrint('[RankedMatch] Already navigating, ignoring duplicate call');
      return;
    }

    _navigatingToGame = true;  // WebSocket 유지를 위해 플래그 설정
    debugPrint('[RankedMatch] Set _navigatingToGame = true');

    if (mounted) {
      debugPrint('[RankedMatch] Navigating to OnlineGameScreen');
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) => OnlineGameScreen(
            wsService: _wsService,
            matchInfo: match,
          ),
        ),
      );
    }
  }

  void _onError(String error) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error), backgroundColor: Colors.red),
      );
    }
  }

  void _joinQueue() {
    debugPrint('[RankedMatch] 대기열 참가 요청');
    _wsService.joinQueue();
    _queueSeconds = 0;
    _queueTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (mounted) {
        setState(() => _queueSeconds++);
      }
    });
  }

  void _leaveQueue() {
    debugPrint('[RankedMatch] 대기열 나가기 요청');
    _wsService.leaveQueue();
    _queueTimer?.cancel();
    setState(() => _queueSeconds = 0);
  }

  String _formatTime(int seconds) {
    final mins = seconds ~/ 60;
    final secs = seconds % 60;
    return '${mins.toString().padLeft(2, '0')}:${secs.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final authService = context.watch<AuthService>();
    final user = authService.currentUser;

    return Scaffold(
      appBar: AppBar(
        title: const Text('랭킹전'),
        backgroundColor: colorScheme.inversePrimary,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (_wsService.matchingState == MatchingState.inQueue) {
              _leaveQueue();
            }
            Navigator.pop(context);
          },
        ),
      ),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // 연결 중
              if (_isConnecting) ...[
                const CircularProgressIndicator(),
                const SizedBox(height: 16),
                const Text('서버에 연결 중...'),
              ]
              // 연결 안됨
              else if (!_wsService.isConnected) ...[
                Icon(
                  Icons.cloud_off,
                  size: 64,
                  color: colorScheme.error,
                ),
                const SizedBox(height: 16),
                Text(
                  '서버에 연결되지 않음',
                  style: TextStyle(color: colorScheme.error),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: _setupWebSocket,
                  icon: const Icon(Icons.refresh),
                  label: const Text('다시 연결'),
                ),
              ]
              // 대기 중 (큐 미참여)
              else if (_wsService.matchingState == MatchingState.idle) ...[
                // 내 정보
                if (user != null) _buildUserInfo(user, colorScheme),
                const SizedBox(height: 48),

                // 매칭 시작 버튼
                _buildStartButton(colorScheme),

                const SizedBox(height: 24),

                // 안내
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    children: [
                      Row(
                        children: [
                          Icon(
                            Icons.info_outline,
                            size: 20,
                            color: colorScheme.primary,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            '랭킹전 안내',
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: colorScheme.primary,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '• 비슷한 점수의 상대와 매칭됩니다\n'
                        '• 승리 시 +20점, 패배 시 -15점\n'
                        '• 매일 오전 9시에 랭킹이 초기화됩니다',
                        style: TextStyle(
                          fontSize: 13,
                          color: colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
              ]
              // 큐에서 대기 중
              else if (_wsService.matchingState == MatchingState.inQueue) ...[
                _buildSearchingAnimation(colorScheme),
                const SizedBox(height: 32),

                Text(
                  '상대를 찾는 중...',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),

                Text(
                  _formatTime(_queueSeconds),
                  style: Theme.of(context).textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: colorScheme.primary,
                  ),
                ),
                const SizedBox(height: 8),

                if (_wsService.queuePosition > 0)
                  Text(
                    '대기열 ${_wsService.queuePosition}번째',
                    style: TextStyle(color: colorScheme.onSurfaceVariant),
                  ),

                const SizedBox(height: 48),

                OutlinedButton.icon(
                  onPressed: _leaveQueue,
                  icon: const Icon(Icons.close),
                  label: const Text('취소'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 32,
                      vertical: 16,
                    ),
                  ),
                ),
              ]
              // 매칭 완료
              else if (_wsService.matchingState == MatchingState.matched) ...[
                const Icon(
                  Icons.check_circle,
                  size: 80,
                  color: Colors.green,
                ),
                const SizedBox(height: 16),
                Text(
                  '매칭 완료!',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 8),
                const CircularProgressIndicator(),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildUserInfo(UserInfo user, ColorScheme colorScheme) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        children: [
          CircleAvatar(
            radius: 40,
            backgroundColor: colorScheme.primaryContainer,
            child: Text(
              user.nickname.isNotEmpty ? user.nickname[0].toUpperCase() : '?',
              style: TextStyle(
                fontSize: 32,
                fontWeight: FontWeight.bold,
                color: colorScheme.onPrimaryContainer,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            user.nickname,
            style: const TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _buildStatChip(
                Icons.star,
                '${user.score.toStringAsFixed(0)}점',
                Colors.amber,
              ),
              const SizedBox(width: 12),
              _buildStatChip(
                Icons.emoji_events,
                '${user.wins}승',
                Colors.green,
              ),
              const SizedBox(width: 12),
              _buildStatChip(
                Icons.close,
                '${user.losses}패',
                Colors.red,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatChip(IconData icon, String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStartButton(ColorScheme colorScheme) {
    return SizedBox(
      width: 200,
      height: 200,
      child: ElevatedButton(
        onPressed: _joinQueue,
        style: ElevatedButton.styleFrom(
          shape: const CircleBorder(),
          backgroundColor: colorScheme.primary,
          foregroundColor: colorScheme.onPrimary,
          elevation: 8,
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.play_arrow,
              size: 64,
              color: colorScheme.onPrimary,
            ),
            const SizedBox(height: 8),
            Text(
              '매칭 시작',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
                color: colorScheme.onPrimary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSearchingAnimation(ColorScheme colorScheme) {
    return SizedBox(
      width: 200,
      height: 200,
      child: AnimatedBuilder(
        animation: _pulseController,
        builder: (context, child) {
          return Stack(
            alignment: Alignment.center,
            children: [
              // 외부 원 (펄스)
              Container(
                width: 200 * (0.8 + _pulseController.value * 0.2),
                height: 200 * (0.8 + _pulseController.value * 0.2),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: colorScheme.primary.withValues(
                    alpha: 0.2 * (1 - _pulseController.value),
                  ),
                ),
              ),
              // 중간 원
              Container(
                width: 150,
                height: 150,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: colorScheme.primary.withValues(alpha: 0.1),
                ),
              ),
              // 내부 원
              Container(
                width: 100,
                height: 100,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: colorScheme.primary,
                ),
                child: Icon(
                  Icons.search,
                  size: 48,
                  color: colorScheme.onPrimary,
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
