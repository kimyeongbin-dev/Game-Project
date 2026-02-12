import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';
import '../services/websocket_service.dart';
import 'online_game_screen.dart';

class FriendMatchScreen extends StatefulWidget {
  const FriendMatchScreen({super.key});

  @override
  State<FriendMatchScreen> createState() => _FriendMatchScreenState();
}

class _FriendMatchScreenState extends State<FriendMatchScreen> {
  late WebSocketService _wsService;
  final _roomCodeController = TextEditingController();
  bool _isConnecting = false;
  String? _roomCodeError;

  @override
  void initState() {
    super.initState();
    _wsService = WebSocketService();
    _setupWebSocket();
  }

  @override
  void dispose() {
    _roomCodeController.dispose();
    _wsService.dispose();
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
    if (mounted) {
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
      setState(() {
        if (error.contains('방을 찾을 수 없') || error.contains('room')) {
          _roomCodeError = error;
        }
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error), backgroundColor: Colors.red),
      );
    }
  }

  void _createRoom() {
    _wsService.createRoom();
  }

  void _joinRoom() {
    final code = _roomCodeController.text.trim().toUpperCase();
    if (code.isEmpty) {
      setState(() => _roomCodeError = '방 코드를 입력하세요');
      return;
    }
    if (code.length != 6) {
      setState(() => _roomCodeError = '방 코드는 6자리입니다');
      return;
    }

    setState(() => _roomCodeError = null);
    _wsService.joinRoom(code);
  }

  void _leaveRoom() {
    _wsService.leaveRoom();
  }

  void _copyRoomCode() {
    if (_wsService.roomCode != null) {
      Clipboard.setData(ClipboardData(text: _wsService.roomCode!));
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('방 코드가 복사되었습니다'),
          duration: Duration(seconds: 2),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('친구 대전'),
        backgroundColor: colorScheme.inversePrimary,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (_wsService.matchingState == MatchingState.inRoom) {
              _leaveRoom();
            }
            Navigator.pop(context);
          },
        ),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
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
                // 대기 중 (방 미생성)
                else if (_wsService.matchingState == MatchingState.idle) ...[
                  _buildCreateOrJoin(colorScheme),
                ]
                // 방에서 대기 중
                else if (_wsService.matchingState == MatchingState.inRoom) ...[
                  _buildWaitingRoom(colorScheme),
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
                    '게임 시작!',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 8),
                  const CircularProgressIndicator(),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCreateOrJoin(ColorScheme colorScheme) {
    return Column(
      children: [
        // 방 만들기 섹션
        Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              children: [
                Icon(
                  Icons.add_circle_outline,
                  size: 48,
                  color: colorScheme.primary,
                ),
                const SizedBox(height: 16),
                Text(
                  '새 방 만들기',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                Text(
                  '방을 만들고 친구에게 코드를 공유하세요',
                  style: TextStyle(color: colorScheme.onSurfaceVariant),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 24),
                FilledButton.icon(
                  onPressed: _createRoom,
                  icon: const Icon(Icons.add),
                  label: const Text('방 만들기'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 32,
                      vertical: 16,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),

        const SizedBox(height: 24),

        // 구분선
        Row(
          children: [
            const Expanded(child: Divider()),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                'OR',
                style: TextStyle(color: colorScheme.onSurfaceVariant),
              ),
            ),
            const Expanded(child: Divider()),
          ],
        ),

        const SizedBox(height: 24),

        // 방 참가 섹션
        Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              children: [
                Icon(
                  Icons.login,
                  size: 48,
                  color: colorScheme.secondary,
                ),
                const SizedBox(height: 16),
                Text(
                  '방 참가하기',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                Text(
                  '친구에게 받은 방 코드를 입력하세요',
                  style: TextStyle(color: colorScheme.onSurfaceVariant),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: _roomCodeController,
                  decoration: InputDecoration(
                    labelText: '방 코드',
                    hintText: 'ABC123',
                    prefixIcon: const Icon(Icons.tag),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    errorText: _roomCodeError,
                  ),
                  textCapitalization: TextCapitalization.characters,
                  maxLength: 6,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 8,
                  ),
                  onChanged: (_) {
                    if (_roomCodeError != null) {
                      setState(() => _roomCodeError = null);
                    }
                  },
                  onSubmitted: (_) => _joinRoom(),
                ),
                const SizedBox(height: 16),
                FilledButton.tonal(
                  onPressed: _joinRoom,
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 32,
                      vertical: 16,
                    ),
                  ),
                  child: const Text('참가하기'),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildWaitingRoom(ColorScheme colorScheme) {
    return Column(
      children: [
        // 방 코드 표시
        Card(
          color: colorScheme.primaryContainer,
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              children: [
                Text(
                  '방 코드',
                  style: TextStyle(
                    color: colorScheme.onPrimaryContainer.withValues(alpha: 0.7),
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      _wsService.roomCode ?? '------',
                      style: TextStyle(
                        fontSize: 48,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 8,
                        color: colorScheme.onPrimaryContainer,
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      onPressed: _copyRoomCode,
                      icon: Icon(
                        Icons.copy,
                        color: colorScheme.onPrimaryContainer,
                      ),
                      tooltip: '복사',
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),

        const SizedBox(height: 32),

        // 대기 중 애니메이션
        const CircularProgressIndicator(),
        const SizedBox(height: 24),

        Text(
          '친구를 기다리는 중...',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 8),
        Text(
          '친구에게 방 코드를 알려주세요',
          style: TextStyle(color: colorScheme.onSurfaceVariant),
        ),

        const SizedBox(height: 48),

        // 취소 버튼
        OutlinedButton.icon(
          onPressed: _leaveRoom,
          icon: const Icon(Icons.close),
          label: const Text('취소'),
          style: OutlinedButton.styleFrom(
            padding: const EdgeInsets.symmetric(
              horizontal: 32,
              vertical: 16,
            ),
          ),
        ),

        const SizedBox(height: 32),

        // 안내
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            children: [
              Icon(
                Icons.info_outline,
                color: colorScheme.primary,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  '친구 대전은 랭킹 점수에 영향을 주지 않습니다',
                  style: TextStyle(
                    fontSize: 13,
                    color: colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
