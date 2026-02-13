import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/game_state.dart';
import '../services/auth_service.dart';

/// 입력 모드 (불리언 플래그 대신 상태 머신)
enum OnlineInputMode { moving, placingWall }
import '../services/websocket_service.dart';
import '../widgets/unified_board_widget.dart';

class OnlineGameScreen extends StatefulWidget {
  final WebSocketService wsService;
  final MatchInfo matchInfo;

  const OnlineGameScreen({
    super.key,
    required this.wsService,
    required this.matchInfo,
  });

  @override
  State<OnlineGameScreen> createState() => _OnlineGameScreenState();
}

class _OnlineGameScreenState extends State<OnlineGameScreen> {
  GameState? _gameState;
  bool _isLoading = false;
  String _message = '';
  OnlineInputMode _inputMode = OnlineInputMode.moving;
  String _wallOrientation = 'horizontal';
  GameEndInfo? _gameEndInfo;
  bool _opponentDisconnected = false;

  @override
  void initState() {
    super.initState();
    debugPrint('[OnlineGame] initState() called');
    _setupCallbacks();

    // 초기 게임 상태가 있으면 설정
    if (widget.matchInfo.initialGameState != null) {
      debugPrint('[OnlineGame] Setting initial game state');
      try {
        _gameState = GameState.fromJson(widget.matchInfo.initialGameState!);
      } catch (e) {
        debugPrint('[OnlineGame] Failed to parse initial game state: $e');
      }
    }

    _message = '게임 시작! ${_isMyTurn ? "당신의 차례입니다" : "상대방의 차례입니다"}';
  }

  @override
  void dispose() {
    debugPrint('[OnlineGame] dispose() called, _gameEndInfo: $_gameEndInfo');
    // 게임 화면을 벗어날 때 WebSocket 정리
    widget.wsService.disconnect();
    super.dispose();
  }

  void _setupCallbacks() {
    widget.wsService.onGameStateUpdate = _onGameStateUpdate;
    widget.wsService.onGameEnd = _onGameEnd;
    widget.wsService.onOpponentDisconnected = _onOpponentDisconnected;
    widget.wsService.onOpponentReconnected = _onOpponentReconnected;
    widget.wsService.onError = _onError;
  }

  void _onGameStateUpdate(Map<String, dynamic> data) {
    if (!mounted) return;

    debugPrint('[OnlineGame] 게임 상태 업데이트 수신');
    try {
      final gameState = GameState.fromJson(data);
      debugPrint('[OnlineGame] 턴: ${gameState.currentTurn}, 턴수: ${gameState.turnCount}');
      setState(() {
        _gameState = gameState;
        _isLoading = false;
        _message = _isMyTurn ? "당신의 차례입니다" : "상대방의 차례입니다";
      });
    } catch (e) {
      debugPrint('[OnlineGame] 게임 상태 파싱 실패: $e');
      debugPrint('[OnlineGame] 받은 데이터: $data');
    }
  }

  void _onGameEnd(GameEndInfo endInfo) {
    if (!mounted) return;

    setState(() {
      _gameEndInfo = endInfo;
      _isLoading = false;
    });

    // 결과 다이얼로그 표시
    _showGameEndDialog(endInfo);
  }

  void _onOpponentDisconnected() {
    if (!mounted) return;
    setState(() {
      _opponentDisconnected = true;
      _message = '상대방 연결이 끊어졌습니다. 재연결 대기 중...';
    });
  }

  void _onOpponentReconnected() {
    if (!mounted) return;
    setState(() {
      _opponentDisconnected = false;
      _message = '상대방이 재연결되었습니다!';
    });
  }

  void _onError(String error) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(error), backgroundColor: Colors.red),
    );
  }

  bool get _isMyTurn {
    if (_gameState == null) {
      return widget.matchInfo.playerNumber == 1;
    }
    return _gameState!.currentTurn == widget.matchInfo.playerNumber;
  }

  bool get _canPlay => _isMyTurn && !_isLoading && _gameEndInfo == null;

  void _movePawn(int row, int col) {
    if (!_canPlay || _inputMode != OnlineInputMode.moving) return;

    debugPrint('[OnlineGame] 말 이동 요청: ($row, $col)');
    setState(() {
      _isLoading = true;
      _message = '이동 중...';
    });

    widget.wsService.movePawn(row, col);
  }

  void _placeWall(int row, int col, String orientation) {
    if (!_canPlay || _inputMode != OnlineInputMode.placingWall) return;

    debugPrint('[OnlineGame] 벽 설치 요청: ($row, $col, $orientation)');
    setState(() {
      _isLoading = true;
      _message = '벽 설치 중...';
    });

    widget.wsService.placeWall(row, col, orientation);
  }

  void _surrender() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('항복'),
        content: const Text('정말 항복하시겠습니까?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(
              backgroundColor: Colors.red,
            ),
            child: const Text('항복'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      widget.wsService.surrender();
    }
  }

  void _showGameEndDialog(GameEndInfo endInfo) {
    final isWinner = endInfo.winner == widget.matchInfo.playerNumber;
    final colorScheme = Theme.of(context).colorScheme;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Row(
          children: [
            Icon(
              isWinner ? Icons.emoji_events : Icons.sentiment_dissatisfied,
              color: isWinner ? Colors.amber : Colors.grey,
              size: 32,
            ),
            const SizedBox(width: 12),
            Text(isWinner ? '승리!' : '패배'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('총 ${endInfo.turnCount}턴'),
            if (endInfo.reason == 'surrender')
              const Text('상대방이 항복했습니다')
            else if (endInfo.reason == 'disconnect')
              const Text('상대방 연결 끊김'),
            const SizedBox(height: 16),
            if (widget.matchInfo.isRanked && endInfo.scoreChange != null) ...[
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text('점수 변화'),
                        Text(
                          '${endInfo.scoreChange! >= 0 ? '+' : ''}${endInfo.scoreChange!.toStringAsFixed(0)}',
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: endInfo.scoreChange! >= 0
                                ? Colors.green
                                : Colors.red,
                          ),
                        ),
                      ],
                    ),
                    if (endInfo.newRank != null) ...[
                      const SizedBox(height: 8),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          const Text('현재 순위'),
                          Text(
                            '${endInfo.newRank}위',
                            style: const TextStyle(fontWeight: FontWeight.bold),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ],
        ),
        actions: [
          FilledButton(
            onPressed: () {
              Navigator.pop(context); // 다이얼로그 닫기
              Navigator.pop(context); // 게임 화면 나가기
            },
            child: const Text('확인'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.matchInfo.isRanked ? '랭킹전' : '친구 대전'),
        backgroundColor: colorScheme.inversePrimary,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            // 게임 중 나가기 확인
            if (_gameEndInfo == null) {
              showDialog(
                context: context,
                builder: (context) => AlertDialog(
                  title: const Text('게임 종료'),
                  content: const Text('게임을 나가면 패배 처리됩니다. 나가시겠습니까?'),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('취소'),
                    ),
                    FilledButton(
                      onPressed: () {
                        Navigator.pop(context);
                        Navigator.pop(context);
                      },
                      child: const Text('나가기'),
                    ),
                  ],
                ),
              );
            } else {
              Navigator.pop(context);
            }
          },
        ),
        actions: [
          if (_gameEndInfo == null)
            IconButton(
              icon: const Icon(Icons.flag_outlined),
              tooltip: '항복',
              onPressed: _surrender,
            ),
        ],
      ),
      body: Column(
        children: [
          // 상대방 정보
          _buildOpponentInfo(colorScheme),

          // 연결 끊김 경고
          if (_opponentDisconnected)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              color: Colors.orange,
              child: const Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.warning, color: Colors.white, size: 18),
                  SizedBox(width: 8),
                  Text(
                    '상대방 연결 끊김 - 재연결 대기 중...',
                    style: TextStyle(color: Colors.white),
                  ),
                ],
              ),
            ),

          // 게임 영역
          Expanded(
            child: _buildGameArea(colorScheme),
          ),

          // 내 정보 & 컨트롤
          _buildMyControls(colorScheme),
        ],
      ),
    );
  }

  Widget _buildOpponentInfo(ColorScheme colorScheme) {
    final isOpponentTurn = !_isMyTurn && _gameEndInfo == null;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: isOpponentTurn
            ? colorScheme.errorContainer
            : colorScheme.surfaceContainerHighest,
        border: Border(
          bottom: BorderSide(color: colorScheme.outlineVariant),
        ),
      ),
      child: Row(
        children: [
          // 상대방 아바타
          CircleAvatar(
            radius: 20,
            backgroundColor:
                isOpponentTurn ? colorScheme.error : colorScheme.secondary,
            child: Text(
              widget.matchInfo.opponentNickname.isNotEmpty
                  ? widget.matchInfo.opponentNickname[0].toUpperCase()
                  : '?',
              style: TextStyle(
                color: isOpponentTurn
                    ? colorScheme.onError
                    : colorScheme.onSecondary,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          const SizedBox(width: 12),

          // 상대방 정보
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.matchInfo.opponentNickname,
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                ),
                if (widget.matchInfo.opponentScore != null)
                  Text(
                    '${widget.matchInfo.opponentScore!.toStringAsFixed(0)}점',
                    style: TextStyle(
                      fontSize: 12,
                      color: colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
          ),

          // 남은 벽 수
          if (_gameState != null)
            _buildWallCount(
              widget.matchInfo.playerNumber == 1
                  ? _gameState!.player2.wallsRemaining
                  : _gameState!.player1.wallsRemaining,
              colorScheme,
            ),

          // 턴 표시
          if (isOpponentTurn)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              decoration: BoxDecoration(
                color: colorScheme.error,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                '차례',
                style: TextStyle(
                  color: colorScheme.onError,
                  fontWeight: FontWeight.bold,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildGameArea(ColorScheme colorScheme) {
    // 게임 상태가 없으면 로딩 표시
    if (_gameState == null) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 16),
            Text('게임 로딩 중...'),
          ],
        ),
      );
    }

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          // 메시지
          if (_message.isNotEmpty)
            Card(
              elevation: 0,
              color: colorScheme.primaryContainer,
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Row(
                  children: [
                    Icon(
                      _isLoading ? Icons.hourglass_empty : Icons.info_outline,
                      size: 18,
                      color: colorScheme.onPrimaryContainer,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        _message,
                        style: TextStyle(color: colorScheme.onPrimaryContainer),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 12),

          // 보드
      UnifiedBoardWidget(
        gameState: _gameState!,
        validMoves: const [], // 온라인에서는 서버에서 검증
        wallMode: _inputMode == OnlineInputMode.placingWall,
        wallOrientation: _wallOrientation,
        onCellTap:
            _canPlay && _inputMode == OnlineInputMode.moving ? _movePawn : null,
        onWallTap: _canPlay && _inputMode == OnlineInputMode.placingWall
            ? _placeWall
            : null,
        enableRotation: false,
        isReplayMode: false,
        // 내 플레이어 번호에 따라 보드 회전
        rotateBoard: widget.matchInfo.playerNumber == 2,
      ),
        ],
      ),
    );
  }

  Widget _buildMyControls(ColorScheme colorScheme) {
    final authService = context.read<AuthService>();
    final myNickname = authService.currentUser?.nickname ?? 'You';
    final myWalls = _gameState != null
        ? (widget.matchInfo.playerNumber == 1
            ? _gameState!.player1.wallsRemaining
            : _gameState!.player2.wallsRemaining)
        : 10;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _isMyTurn && _gameEndInfo == null
            ? colorScheme.primaryContainer
            : colorScheme.surfaceContainerHighest,
        border: Border(
          top: BorderSide(color: colorScheme.outlineVariant),
        ),
      ),
      child: Column(
        children: [
          // 내 정보
          Row(
            children: [
              CircleAvatar(
                radius: 20,
                backgroundColor:
                    _isMyTurn ? colorScheme.primary : colorScheme.secondary,
                child: Text(
                  myNickname.isNotEmpty ? myNickname[0].toUpperCase() : 'Y',
                  style: TextStyle(
                    color: _isMyTurn
                        ? colorScheme.onPrimary
                        : colorScheme.onSecondary,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      myNickname,
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                    Text(
                      'Player ${widget.matchInfo.playerNumber}',
                      style: TextStyle(
                        fontSize: 12,
                        color: _isMyTurn
                            ? colorScheme.onPrimaryContainer
                            : colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              _buildWallCount(myWalls, colorScheme),
              if (_isMyTurn && _gameEndInfo == null)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  decoration: BoxDecoration(
                    color: colorScheme.primary,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    '내 차례',
                    style: TextStyle(
                      color: colorScheme.onPrimary,
                      fontWeight: FontWeight.bold,
                      fontSize: 12,
                    ),
                  ),
                ),
            ],
          ),

          // 컨트롤 (내 차례일 때만)
          if (_canPlay && myWalls > 0) ...[
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                FilledButton.tonal(
                  onPressed: () {
                    debugPrint('[OnlineGame] 모드 변경: ${_wallMode ? "벽→이동" : "이동→벽"}');
                    setState(() => _wallMode = !_wallMode);
                  },
                  style: FilledButton.styleFrom(
                    backgroundColor: _wallMode
                        ? colorScheme.secondaryContainer
                        : colorScheme.primaryContainer,
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        _wallMode ? Icons.directions_walk : Icons.fence,
                        size: 18,
                      ),
                      const SizedBox(width: 8),
                      Text(_wallMode ? '이동 모드' : '벽 모드'),
                    ],
                  ),
                ),
                if (_wallMode) ...[
                  const SizedBox(width: 16),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(
                        value: 'horizontal',
                        icon: Icon(Icons.horizontal_rule, size: 18),
                        label: Text('수평'),
                      ),
                      ButtonSegment(
                        value: 'vertical',
                        icon: Icon(Icons.more_vert, size: 18),
                        label: Text('수직'),
                      ),
                    ],
                    selected: {_wallOrientation},
                    onSelectionChanged: (Set<String> selection) {
                      debugPrint('[OnlineGame] 벽 방향 변경: ${selection.first}');
                      setState(() => _wallOrientation = selection.first);
                    },
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildWallCount(int count, ColorScheme colorScheme) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      margin: const EdgeInsets.only(right: 8),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.fence, size: 14, color: colorScheme.onSurfaceVariant),
          const SizedBox(width: 4),
          Text(
            '$count',
            style: TextStyle(
              fontWeight: FontWeight.bold,
              color: colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}
