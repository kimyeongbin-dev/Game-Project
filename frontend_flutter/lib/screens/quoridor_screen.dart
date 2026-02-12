import 'package:flutter/material.dart';
import '../models/game_state.dart';
import '../services/api_service.dart';
import '../widgets/unified_board_widget.dart';

/// 쿼리도 게임 화면
class QuoridorScreen extends StatefulWidget {
  final String initialMode;

  const QuoridorScreen({
    super.key,
    this.initialMode = 'vs_ai',
  });

  @override
  State<QuoridorScreen> createState() => _QuoridorScreenState();
}

class _QuoridorScreenState extends State<QuoridorScreen> {
  final QuoridorApiService _apiService = QuoridorApiService();

  GameState? _gameState;
  ValidMoves? _validMoves;
  bool _isLoading = false;
  String? _errorMessage;
  String _message = '';

  bool _wallMode = false;
  String _wallOrientation = 'horizontal';

  String _playerName = 'Player';
  String _player2Name = 'Player 2';
  String _difficulty = 'normal';
  late String _gameMode; // 'vs_ai' or 'local_2p'

  // 활성 세션 목록 (게임 복구용)
  List<SessionInfo> _activeSessions = [];
  bool _isLoadingSessions = false;

  // 보드 회전 기능
  bool _enableRotation = false;

  // 리플레이 모드
  bool _isReplayMode = false;
  int _replayStep = -1; // -1 = 초기 상태
  int _totalMoves = 0;
  GameState? _replayGameState; // 리플레이 중 표시할 게임 상태
  List<MoveRecord> _replayMoves = [];

  @override
  void initState() {
    super.initState();
    _gameMode = widget.initialMode;
    _loadActiveSessions();
  }

  @override
  void dispose() {
    _apiService.dispose();
    super.dispose();
  }

  /// 서버에서 진행 중인 게임 세션 목록 로드
  Future<void> _loadActiveSessions() async {
    setState(() {
      _isLoadingSessions = true;
    });

    try {
      final response = await _apiService.getActiveSessions(limit: 10);
      setState(() {
        _activeSessions = response.sessions;
      });
    } catch (e) {
      // 세션 로드 실패해도 게임 진행에는 문제 없음
      debugPrint('Failed to load active sessions: $e');
    } finally {
      setState(() {
        _isLoadingSessions = false;
      });
    }
  }

  /// 기존 게임 복구
  Future<void> _resumeGame(String gameId) async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final gameState = await _apiService.syncGameState(gameId);
      if (gameState != null) {
        setState(() {
          _gameState = gameState;
          _message = '게임이 복구되었습니다!';
          _wallMode = false;
        });
        await _loadValidMoves();
      } else {
        setState(() {
          _errorMessage = '게임을 복구할 수 없습니다.';
        });
        // 세션 목록 갱신
        await _loadActiveSessions();
      }
    } catch (e) {
      setState(() {
        _errorMessage = e.toString();
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  Future<void> _createNewGame() async {
    debugPrint('[Quoridor] 새 게임 생성: 모드=$_gameMode, 난이도=$_difficulty');
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final response = await _apiService.createGame(
        playerName: _playerName,
        player2Name: _player2Name,
        aiDifficulty: _difficulty,
        gameMode: _gameMode,
      );
      final gameId = response['game_id'] as String;
      debugPrint('[Quoridor] 게임 생성됨: $gameId');
      final gameState = await _apiService.getGame(gameId);

      setState(() {
        _gameState = gameState;
        _message = _gameMode == 'local_2p'
            ? '로컬 2인 게임이 시작되었습니다!'
            : '게임이 시작되었습니다!';
        _wallMode = false;
      });

      await _loadValidMoves();
    } catch (e) {
      setState(() {
        _errorMessage = e.toString();
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  Future<void> _loadValidMoves() async {
    if (_gameState == null || _gameState!.isFinished) return;
    // VS AI 모드에서는 Player 1 턴에만 로드
    // Local 2P 모드에서는 항상 로드
    if (_gameState!.isVsAI && _gameState!.currentTurn != 1) return;

    try {
      final validMoves = await _apiService.getValidMoves(_gameState!.gameId);
      setState(() {
        _validMoves = validMoves;
      });
    } catch (e) {
      // 에러 무시
    }
  }

  Future<void> _movePawn(int row, int col) async {
    if (_gameState == null) return;

    debugPrint('[Quoridor] 말 이동 요청: ($row, $col)');
    setState(() {
      _isLoading = true;
    });

    try {
      final response = await _apiService.movePawn(
        _gameState!.gameId,
        row,
        col,
      );

      if (response.success && response.gameState != null) {
        debugPrint('[Quoridor] 말 이동 성공: 턴 ${response.gameState!.turnCount}');
        setState(() {
          _gameState = response.gameState;
          _message = response.message;
          _validMoves = null;
        });

        // VS AI 모드일 때만 AI 턴 처리
        if (_gameState!.isVsAI) {
          await _handleAITurn();
        } else {
          // Local 2P 모드: 다음 플레이어의 유효 이동 로드
          await _loadValidMoves();
        }
      } else {
        setState(() {
          _message = response.message;
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = e.toString();
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  Future<void> _placeWall(int row, int col, String orientation) async {
    if (_gameState == null) return;

    debugPrint('[Quoridor] 벽 설치 요청: ($row, $col, $orientation)');
    setState(() {
      _isLoading = true;
    });

    try {
      final response = await _apiService.placeWall(
        _gameState!.gameId,
        row,
        col,
        orientation,
      );

      if (response.success && response.gameState != null) {
        debugPrint('[Quoridor] 벽 설치 성공: 남은 벽 P1=${response.gameState!.player1.wallsRemaining}');
        setState(() {
          _gameState = response.gameState;
          _message = response.message;
          _wallMode = false;
          _validMoves = null;
        });

        // VS AI 모드일 때만 AI 턴 처리
        if (_gameState!.isVsAI) {
          await _handleAITurn();
        } else {
          // Local 2P 모드: 다음 플레이어의 유효 이동 로드
          await _loadValidMoves();
        }
      } else {
        setState(() {
          _message = response.message;
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = e.toString();
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  Future<void> _handleAITurn() async {
    if (_gameState == null || _gameState!.isFinished) return;
    if (_gameState!.currentTurn != 2) {
      await _loadValidMoves();
      return;
    }

    debugPrint('[Quoridor] AI 턴 시작');
    setState(() {
      _message = 'AI가 생각 중...';
    });

    await Future.delayed(const Duration(milliseconds: 500));

    try {
      final response = await _apiService.aiMove(_gameState!.gameId);

      if (response.success && response.gameState != null) {
        final action = response.action;
        String actionMsg = '';
        if (action != null) {
          if (action.type == 'move') {
            actionMsg = 'AI가 (${action.row}, ${action.col})로 이동';
            debugPrint('[Quoridor] AI 이동: (${action.row}, ${action.col})');
          } else {
            actionMsg = 'AI가 벽을 설치';
            debugPrint('[Quoridor] AI 벽 설치: (${action.row}, ${action.col}, ${action.orientation})');
          }
        }

        setState(() {
          _gameState = response.gameState;
          _message = actionMsg;
        });

        await _loadValidMoves();
      }
    } catch (e) {
      debugPrint('[Quoridor] AI 턴 에러: $e');
      setState(() {
        _errorMessage = e.toString();
      });
    }
  }

  /// 메인 화면으로 돌아가기
  void _goToMain() {
    setState(() {
      _gameState = null;
      _validMoves = null;
      _message = '';
      _errorMessage = null;
      _wallMode = false;
    });
    _loadActiveSessions();
  }

  /// 현재 게임 포기
  Future<void> _abandonGame() async {
    if (_gameState == null) return;

    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('게임 포기'),
        content: const Text('현재 게임을 포기하시겠습니까?\n게임 기록이 삭제됩니다.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('포기'),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      await _apiService.abandonGame(_gameState!.gameId);
      _goToMain();
    } catch (e) {
      setState(() {
        _errorMessage = '게임 포기 실패: $e';
      });
    }
  }

  /// 세션 삭제
  Future<void> _deleteSession(String gameId) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('게임 삭제'),
        content: const Text('이 게임을 삭제하시겠습니까?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
            ),
            child: const Text('삭제'),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      await _apiService.deleteGame(gameId);
      await _loadActiveSessions();
    } catch (e) {
      setState(() {
        _errorMessage = '게임 삭제 실패: $e';
      });
    }
  }

  /// 보드 회전 토글
  void _toggleRotation() {
    setState(() {
      _enableRotation = !_enableRotation;
    });
  }

  /// 리플레이 모드 진입
  Future<void> _enterReplayMode() async {
    if (_gameState == null) return;

    setState(() {
      _isLoading = true;
    });

    try {
      final movesResponse = await _apiService.getReplayMoves(_gameState!.gameId);
      setState(() {
        _isReplayMode = true;
        _replayMoves = movesResponse.moves;
        _totalMoves = movesResponse.totalMoves;
        _replayStep = _totalMoves - 1; // 마지막 수에서 시작
        _replayGameState = _gameState; // 현재 상태 저장
        _message = '리플레이 모드: ${_replayStep + 1} / $_totalMoves';
      });
    } catch (e) {
      setState(() {
        _errorMessage = '리플레이 로드 실패: $e';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  /// 리플레이 모드 종료
  void _exitReplayMode() {
    setState(() {
      _isReplayMode = false;
      _replayStep = -1;
      _replayMoves = [];
      _replayGameState = null;
      _message = '';
    });
  }

  /// 리플레이: 이전 수로 이동
  Future<void> _replayPrevious() async {
    if (!_isReplayMode || _replayStep < 0) return;

    setState(() {
      _isLoading = true;
    });

    try {
      final newStep = _replayStep - 1;
      final stateResponse = await _apiService.getReplayState(
        _gameState!.gameId,
        newStep,
      );

      setState(() {
        _replayStep = newStep;
        _replayGameState = GameState.fromJson(stateResponse.gameState);
        _message = newStep < 0
            ? '리플레이 모드: 초기 상태'
            : '리플레이 모드: ${newStep + 1} / $_totalMoves';
      });
    } catch (e) {
      setState(() {
        _errorMessage = '상태 로드 실패: $e';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  /// 리플레이: 다음 수로 이동
  Future<void> _replayNext() async {
    if (!_isReplayMode || _replayStep >= _totalMoves - 1) return;

    setState(() {
      _isLoading = true;
    });

    try {
      final newStep = _replayStep + 1;
      final stateResponse = await _apiService.getReplayState(
        _gameState!.gameId,
        newStep,
      );

      setState(() {
        _replayStep = newStep;
        _replayGameState = GameState.fromJson(stateResponse.gameState);
        _message = '리플레이 모드: ${newStep + 1} / $_totalMoves';
      });
    } catch (e) {
      setState(() {
        _errorMessage = '상태 로드 실패: $e';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  /// 리플레이: 처음으로 이동
  Future<void> _replayFirst() async {
    if (!_isReplayMode || _replayStep < 0) return;

    setState(() {
      _isLoading = true;
    });

    try {
      final stateResponse = await _apiService.getReplayState(
        _gameState!.gameId,
        -1, // 초기 상태
      );

      setState(() {
        _replayStep = -1;
        _replayGameState = GameState.fromJson(stateResponse.gameState);
        _message = '리플레이 모드: 초기 상태';
      });
    } catch (e) {
      setState(() {
        _errorMessage = '상태 로드 실패: $e';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  /// 리플레이: 마지막으로 이동
  Future<void> _replayLast() async {
    if (!_isReplayMode || _replayStep >= _totalMoves - 1) return;

    setState(() {
      _isLoading = true;
    });

    try {
      final stateResponse = await _apiService.getReplayState(
        _gameState!.gameId,
        _totalMoves - 1,
      );

      setState(() {
        _replayStep = _totalMoves - 1;
        _replayGameState = GameState.fromJson(stateResponse.gameState);
        _message = '리플레이 모드: $_totalMoves / $_totalMoves';
      });
    } catch (e) {
      setState(() {
        _errorMessage = '상태 로드 실패: $e';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  void _toggleWallMode() {
    debugPrint('[Quoridor] 모드 변경: ${_wallMode ? "벽→이동" : "이동→벽"}');
    setState(() {
      _wallMode = !_wallMode;
    });
  }

  void _setWallOrientation(String orientation) {
    debugPrint('[Quoridor] 벽 방향 변경: $orientation');
    setState(() {
      _wallOrientation = orientation;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_isReplayMode ? '쿼리도 - 리플레이' : '쿼리도'),
        leading: _gameState != null
            ? IconButton(
                icon: const Icon(Icons.home),
                tooltip: '메인으로',
                onPressed: _isReplayMode ? _exitReplayMode : _goToMain,
              )
            : null,
        actions: [
          // 보드 회전 토글 (게임 중일 때만)
          if (_gameState != null && !_isReplayMode)
            IconButton(
              icon: Icon(
                _enableRotation ? Icons.screen_rotation : Icons.screen_lock_rotation,
                color: _enableRotation ? Colors.green : null,
              ),
              tooltip: _enableRotation ? '회전 끄기' : '회전 켜기',
              onPressed: _toggleRotation,
            ),
          // 리플레이 버튼 (게임 종료 후 또는 진행 중)
          if (_gameState != null && !_isReplayMode && _gameState!.turnCount > 0)
            IconButton(
              icon: const Icon(Icons.replay),
              tooltip: '리플레이',
              onPressed: _isLoading ? null : _enterReplayMode,
            ),
          // 게임 포기 (게임 진행 중일 때만)
          if (_gameState != null && !_gameState!.isFinished && !_isReplayMode)
            IconButton(
              icon: const Icon(Icons.flag_outlined),
              tooltip: '게임 포기',
              onPressed: _isLoading ? null : _abandonGame,
            ),
          if (_gameState == null)
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: '새로고침',
              onPressed: _isLoading ? null : _loadActiveSessions,
            ),
          IconButton(
            icon: const Icon(Icons.help_outline),
            onPressed: () => _showRulesDialog(context),
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_gameState == null) {
      return _buildSetupScreen();
    }

    final colorScheme = Theme.of(context).colorScheme;
    // 리플레이 모드에서는 리플레이 상태를, 아니면 실제 게임 상태를 사용
    final displayState = _isReplayMode && _replayGameState != null
        ? _replayGameState!
        : _gameState!;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          GameInfoCard(gameState: displayState),
          const SizedBox(height: 12),
          if (_message.isNotEmpty)
            Card(
              elevation: 0,
              color: _isReplayMode
                  ? colorScheme.tertiaryContainer
                  : colorScheme.primaryContainer,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Row(
                  children: [
                    Icon(
                      _isReplayMode ? Icons.replay : Icons.info_outline,
                      size: 18,
                      color: _isReplayMode
                          ? colorScheme.onTertiaryContainer
                          : colorScheme.onPrimaryContainer,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        _message,
                        style: TextStyle(
                          color: _isReplayMode
                              ? colorScheme.onTertiaryContainer
                              : colorScheme.onPrimaryContainer,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 12),
          // 리플레이 컨트롤 또는 게임 컨트롤
          if (_isReplayMode)
            _buildReplayControls()
          else if (!displayState.isFinished && displayState.isPlayerTurn)
            _buildM3Controls(),
          const SizedBox(height: 12),
          if (_isLoading)
            const Padding(
              padding: EdgeInsets.all(32),
              child: CircularProgressIndicator(),
            )
          else
            UnifiedBoardWidget(
              gameState: displayState,
              validMoves: _isReplayMode ? [] : (_validMoves?.pawnMoves ?? []),
              wallMode: _isReplayMode ? false : _wallMode,
              wallOrientation: _wallOrientation,
              onCellTap: _isReplayMode || !displayState.isPlayerTurn || _wallMode
                  ? null
                  : _movePawn,
              onWallTap: _isReplayMode || !displayState.isPlayerTurn || !_wallMode
                  ? null
                  : _placeWall,
              enableRotation: _enableRotation,
              isReplayMode: _isReplayMode,
            ),
          if (_errorMessage != null)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Card(
                color: colorScheme.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Row(
                    children: [
                      Icon(Icons.error_outline, color: colorScheme.onErrorContainer),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _errorMessage!,
                          style: TextStyle(color: colorScheme.onErrorContainer),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// 리플레이 컨트롤 UI
  Widget _buildReplayControls() {
    final colorScheme = Theme.of(context).colorScheme;

    return Card(
      elevation: 0,
      color: colorScheme.tertiaryContainer,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // 처음으로
            IconButton(
              onPressed: _replayStep > -1 && !_isLoading ? _replayFirst : null,
              icon: const Icon(Icons.first_page),
              tooltip: '처음으로',
            ),
            // 이전
            IconButton(
              onPressed: _replayStep > -1 && !_isLoading ? _replayPrevious : null,
              icon: const Icon(Icons.navigate_before),
              tooltip: '이전',
            ),
            const SizedBox(width: 16),
            // 현재 위치 표시
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(
                color: colorScheme.tertiary.withOpacity(0.2),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                _replayStep < 0 ? '초기' : '${_replayStep + 1} / $_totalMoves',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  color: colorScheme.onTertiaryContainer,
                ),
              ),
            ),
            const SizedBox(width: 16),
            // 다음
            IconButton(
              onPressed: _replayStep < _totalMoves - 1 && !_isLoading ? _replayNext : null,
              icon: const Icon(Icons.navigate_next),
              tooltip: '다음',
            ),
            // 마지막으로
            IconButton(
              onPressed: _replayStep < _totalMoves - 1 && !_isLoading ? _replayLast : null,
              icon: const Icon(Icons.last_page),
              tooltip: '마지막으로',
            ),
            const SizedBox(width: 16),
            // 리플레이 종료
            FilledButton.tonal(
              onPressed: _exitReplayMode,
              child: const Text('종료'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSetupScreen() {
    final colorScheme = Theme.of(context).colorScheme;

    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: colorScheme.primaryContainer,
                shape: BoxShape.circle,
              ),
              child: Icon(
                Icons.grid_view_rounded,
                size: 56,
                color: colorScheme.onPrimaryContainer,
              ),
            ),
            const SizedBox(height: 24),
            Text(
              '쿼리도',
              style: TextStyle(
                fontSize: 32,
                fontWeight: FontWeight.bold,
                color: colorScheme.onSurface,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '벽을 세워 상대를 막는 전략 게임',
              style: TextStyle(
                fontSize: 14,
                color: colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 40),
            Card(
              elevation: 0,
              color: colorScheme.surfaceContainerLow,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  children: [
                    // 게임 모드 선택
                    SegmentedButton<String>(
                      segments: const [
                        ButtonSegment(
                          value: 'vs_ai',
                          icon: Icon(Icons.smart_toy_outlined),
                          label: Text('AI 대전'),
                        ),
                        ButtonSegment(
                          value: 'local_2p',
                          icon: Icon(Icons.people_outline),
                          label: Text('로컬 2인'),
                        ),
                      ],
                      selected: {_gameMode},
                      onSelectionChanged: (Set<String> selection) {
                        debugPrint('[Quoridor] 게임 모드 변경: ${selection.first}');
                        setState(() {
                          _gameMode = selection.first;
                        });
                      },
                    ),
                    const SizedBox(height: 20),
                    TextField(
                      decoration: InputDecoration(
                        labelText: _gameMode == 'local_2p' ? 'Player 1 이름' : '플레이어 이름',
                        hintText: 'Player',
                        prefixIcon: const Icon(Icons.person_outline),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                        filled: true,
                        fillColor: colorScheme.surface,
                      ),
                      onChanged: (value) =>
                          _playerName = value.isEmpty ? 'Player' : value,
                    ),
                    // 로컬 2인 모드일 때 Player 2 이름 입력
                    if (_gameMode == 'local_2p') ...[
                      const SizedBox(height: 16),
                      TextField(
                        decoration: InputDecoration(
                          labelText: 'Player 2 이름',
                          hintText: 'Player 2',
                          prefixIcon: const Icon(Icons.person_outline),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                          filled: true,
                          fillColor: colorScheme.surface,
                        ),
                        onChanged: (value) =>
                            _player2Name = value.isEmpty ? 'Player 2' : value,
                      ),
                    ],
                    // AI 모드일 때만 난이도 선택
                    if (_gameMode == 'vs_ai') ...[
                      const SizedBox(height: 16),
                      DropdownButtonFormField<String>(
                        value: _difficulty,
                        decoration: InputDecoration(
                          labelText: 'AI 난이도',
                          prefixIcon: const Icon(Icons.psychology_outlined),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                          filled: true,
                          fillColor: colorScheme.surface,
                        ),
                        items: const [
                          DropdownMenuItem(value: 'easy', child: Text('쉬움')),
                          DropdownMenuItem(value: 'normal', child: Text('보통')),
                          DropdownMenuItem(value: 'hard', child: Text('어려움')),
                        ],
                        onChanged: (value) {
                          if (value != null) {
                            debugPrint('[Quoridor] AI 난이도 변경: $value');
                            setState(() => _difficulty = value);
                          }
                        },
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 32),
            FilledButton.icon(
              onPressed: _isLoading ? null : _createNewGame,
              icon: _isLoading
                  ? SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: colorScheme.onPrimary,
                      ),
                    )
                  : const Icon(Icons.play_arrow),
              label: const Text('게임 시작'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 40,
                  vertical: 16,
                ),
              ),
            ),
            // 진행 중인 게임 세션 목록 표시
            if (_activeSessions.isNotEmpty) ...[
              const SizedBox(height: 40),
              Row(
                children: [
                  const Expanded(child: Divider()),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Text(
                      '또는 이어하기',
                      style: TextStyle(
                        color: colorScheme.onSurfaceVariant,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                  const Expanded(child: Divider()),
                ],
              ),
              const SizedBox(height: 16),
              _buildActiveSessionsList(colorScheme),
            ],
            if (_isLoadingSessions)
              const Padding(
                padding: EdgeInsets.all(16),
                child: CircularProgressIndicator(),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildActiveSessionsList(ColorScheme colorScheme) {
    return Column(
      children: _activeSessions.map((session) {
        final isAI = session.gameMode == 'vs_ai';
        final turnText = session.currentTurn == 1
            ? '${session.player1Name}의 차례'
            : '${session.player2Name}의 차례';

        return Card(
          elevation: 0,
          color: colorScheme.surfaceContainerLow,
          margin: const EdgeInsets.only(bottom: 8),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          child: ListTile(
            leading: Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: isAI
                    ? colorScheme.primaryContainer
                    : colorScheme.secondaryContainer,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(
                isAI ? Icons.smart_toy_outlined : Icons.people_outline,
                color: isAI
                    ? colorScheme.onPrimaryContainer
                    : colorScheme.onSecondaryContainer,
              ),
            ),
            title: Text(
              '${session.player1Name} vs ${session.player2Name}',
              style: const TextStyle(fontWeight: FontWeight.w500),
            ),
            subtitle: Text(
              'Turn ${session.turnCount} - $turnText',
              style: TextStyle(
                color: colorScheme.onSurfaceVariant,
                fontSize: 12,
              ),
            ),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                FilledButton.tonal(
                  onPressed: _isLoading ? null : () => _resumeGame(session.gameId),
                  child: const Text('이어하기'),
                ),
                const SizedBox(width: 8),
                IconButton(
                  icon: Icon(
                    Icons.delete_outline,
                    color: colorScheme.error,
                  ),
                  tooltip: '삭제',
                  onPressed: _isLoading ? null : () => _deleteSession(session.gameId),
                ),
              ],
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildM3Controls() {
    final hasWalls = _gameState!.player1.wallsRemaining > 0;
    final colorScheme = Theme.of(context).colorScheme;

    return Card(
      elevation: 0,
      color: colorScheme.surfaceContainerLow,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            FilledButton.tonal(
              onPressed: hasWalls ? _toggleWallMode : null,
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
                  _setWallOrientation(selection.first);
                },
              ),
            ],
          ],
        ),
      ),
    );
  }

  void _showRulesDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('게임 규칙'),
        content: const SingleChildScrollView(
          child: Text('''
목표: 반대편 끝에 먼저 도달하면 승리!

당신 (P1): 하단에서 시작 → 상단 도달 시 승리
AI: 상단에서 시작 → 하단 도달 시 승리

턴마다 선택:
1. 이동: 상하좌우 1칸 이동
2. 벽 설치: 남은 벽으로 상대 경로 방해

규칙:
- 벽은 2칸 길이
- 상대방 경로를 완전히 막을 수 없음
- 상대방 위에서 점프 가능
'''),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('확인'),
          ),
        ],
      ),
    );
  }
}
