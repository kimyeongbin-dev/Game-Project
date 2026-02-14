import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/game_state.dart';
import '../services/auth_service.dart';
import '../services/websocket_service.dart';
import '../widgets/unified_board_widget.dart';

/// 입력 모드 (상태 머신 패턴 적용)
enum OnlineInputMode { moving, placingWall }

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
    _setupCallbacks();

    if (widget.matchInfo.initialGameState != null) {
      try {
        _gameState = GameState.fromJson(widget.matchInfo.initialGameState!);
      } catch (e) {
        debugPrint('[OnlineGame] 초기 상태 파싱 실패: $e');
      }
    }
    _message = '게임 시작! ${_isMyTurn ? "당신의 차례입니다" : "상대방의 차례입니다"}';
  }

  @override
  void dispose() {
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
    try {
      final gameState = GameState.fromJson(data);
      setState(() {
        _gameState = gameState;
        _isLoading = false;
        _message = _isMyTurn ? "당신의 차례입니다" : "상대방의 차례입니다";
      });
    } catch (e) {
      debugPrint('[OnlineGame] 업데이트 실패: $e');
    }
  }

  void _onGameEnd(GameEndInfo endInfo) {
    if (!mounted) return;
    setState(() {
      _gameEndInfo = endInfo;
      _isLoading = false;
    });
    _showGameEndDialog(endInfo);
  }

  void _onOpponentDisconnected() {
    if (!mounted) return;
    setState(() {
      _opponentDisconnected = true;
      _message = '상대방 연결 끊김 - 재연결 대기 중...';
    });
  }

  void _onOpponentReconnected() {
    if (!mounted) return;
    setState(() {
      _opponentDisconnected = false;
      _message = '상대방 재연결 완료!';
    });
  }

  void _onError(String error) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(error), backgroundColor: Colors.red),
    );
  }

  bool get _isMyTurn {
    if (_gameState == null) return widget.matchInfo.playerNumber == 1;
    return _gameState!.currentTurn == widget.matchInfo.playerNumber;
  }

  bool get _canPlay => _isMyTurn && !_isLoading && _gameEndInfo == null;

  void _movePawn(int row, int col) {
    if (!_canPlay || _inputMode != OnlineInputMode.moving) return;
    setState(() {
      _isLoading = true;
      _message = '이동 중...';
    });
    widget.wsService.movePawn(row, col);
  }

  void _placeWall(int row, int col, String orientation) {
    if (!_canPlay || _inputMode != OnlineInputMode.placingWall) return;
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
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('취소')),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('항복'),
          ),
        ],
      ),
    );
    if (confirmed == true) widget.wsService.surrender();
  }

  void _showGameEndDialog(GameEndInfo endInfo) {
    final isWinner = endInfo.winner == widget.matchInfo.playerNumber;
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Row(
          children: [
            Icon(isWinner ? Icons.emoji_events : Icons.sentiment_dissatisfied, 
                 color: isWinner ? Colors.amber : Colors.grey),
            const SizedBox(width: 12),
            Text(isWinner ? '승리!' : '패배'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('총 ${endInfo.turnCount}턴'),
            const SizedBox(height: 16),
            if (widget.matchInfo.isRanked && endInfo.scoreChange != null)
              Text('점수 변화: ${endInfo.scoreChange! >= 0 ? "+" : ""}${endInfo.scoreChange!.toStringAsFixed(0)}'),
          ],
        ),
        actions: [
          FilledButton(
            onPressed: () {
              Navigator.pop(context);
              Navigator.pop(context);
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
        actions: [
          if (_gameEndInfo == null)
            IconButton(icon: const Icon(Icons.flag_outlined), onPressed: _surrender),
        ],
      ),
      body: Column(
        children: [
          _buildOpponentInfo(colorScheme),
          if (_opponentDisconnected)
            Container(
              padding: const EdgeInsets.all(8),
              color: Colors.orange,
              child: const Center(child: Text('상대방 연결 끊김 - 재연결 대기 중...', style: TextStyle(color: Colors.white))),
            ),
          Expanded(child: _buildGameArea(colorScheme)),
          _buildMyControls(colorScheme),
        ],
      ),
    );
  }

  Widget _buildOpponentInfo(ColorScheme colorScheme) {
    final isOpponentTurn = !_isMyTurn && _gameEndInfo == null;
    return Container(
      padding: const EdgeInsets.all(16),
      color: isOpponentTurn ? colorScheme.errorContainer : colorScheme.surfaceVariant,
      child: Row(
        children: [
          CircleAvatar(backgroundColor: isOpponentTurn ? colorScheme.error : colorScheme.secondary),
          const SizedBox(width: 12),
          Text(widget.matchInfo.opponentNickname, style: const TextStyle(fontWeight: FontWeight.bold)),
          const Spacer(),
          if (_gameState != null) _buildWallCount(widget.matchInfo.playerNumber == 1 ? _gameState!.player2.wallsRemaining : _gameState!.player1.wallsRemaining, colorScheme),
        ],
      ),
    );
  }

  Widget _buildGameArea(ColorScheme colorScheme) {
    if (_gameState == null) return const Center(child: CircularProgressIndicator());
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          if (_message.isNotEmpty)
            Card(
              color: colorScheme.primaryContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(children: [const Icon(Icons.info_outline, size: 18), const SizedBox(width: 8), Text(_message)]),
              ),
            ),
          const SizedBox(height: 12),
          UnifiedBoardWidget(
            gameState: _gameState!,
            validMoves: const [],
            wallMode: _inputMode == OnlineInputMode.placingWall,
            wallOrientation: _wallOrientation,
            onCellTap: _canPlay && _inputMode == OnlineInputMode.moving ? _movePawn : null,
            onWallTap: _canPlay && _inputMode == OnlineInputMode.placingWall ? _placeWall : null,
            rotateBoard: widget.matchInfo.playerNumber == 2,
          ),
        ],
      ),
    );
  }

  Widget _buildMyControls(ColorScheme colorScheme) {
    final isPlacingWall = _inputMode == OnlineInputMode.placingWall;
    final myWalls = _gameState != null ? (widget.matchInfo.playerNumber == 1 ? _gameState!.player1.wallsRemaining : _gameState!.player2.wallsRemaining) : 0;

    return Container(
      padding: const EdgeInsets.all(16),
      color: _isMyTurn ? colorScheme.primaryContainer : colorScheme.surfaceVariant,
      child: Column(
        children: [
          Row(
            children: [
              const CircleAvatar(child: Icon(Icons.person)),
              const SizedBox(width: 12),
              const Text('나', style: TextStyle(fontWeight: FontWeight.bold)),
              const Spacer(),
              _buildWallCount(myWalls, colorScheme),
            ],
          ),
          if (_canPlay && myWalls > 0) ...[
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                FilledButton.tonal(
                  onPressed: () => setState(() => _inputMode = isPlacingWall ? OnlineInputMode.moving : OnlineInputMode.placingWall),
                  child: Row(children: [Icon(isPlacingWall ? Icons.directions_walk : Icons.fence), const SizedBox(width: 8), Text(isPlacingWall ? '이동 모드 전환' : '벽 모드 전환')]),
                ),
                if (isPlacingWall) ...[
                  const SizedBox(width: 16),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'horizontal', label: Text('수평')),
                      ButtonSegment(value: 'vertical', label: Text('수직')),
                    ],
                    selected: {_wallOrientation},
                    onSelectionChanged: (set) => setState(() => _wallOrientation = set.first),
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
      decoration: BoxDecoration(color: colorScheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
      child: Row(children: [const Icon(Icons.fence, size: 14), const SizedBox(width: 4), Text('$count')]),
    );
  }
}