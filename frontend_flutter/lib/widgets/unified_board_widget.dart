import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../models/game_state.dart';

/// 17x17 통합 쿼리도 보드 위젯
/// 셀과 벽을 하나의 그리드에서 동시에 표시
/// 턴 변경 시 180도 회전 애니메이션 지원
class UnifiedBoardWidget extends StatefulWidget {
  final GameState gameState;
  final List<Position> validMoves;
  final bool wallMode;
  final String wallOrientation;
  final Function(int row, int col)? onCellTap;
  final Function(int row, int col, String orientation)? onWallTap;
  final bool enableRotation; // 회전 기능 On/Off (턴마다 애니메이션)
  final bool isReplayMode; // 리플레이 모드 여부
  final bool rotateBoard; // 고정 180도 회전 (온라인 Player 2용)

  const UnifiedBoardWidget({
    super.key,
    required this.gameState,
    this.validMoves = const [],
    this.wallMode = false,
    this.wallOrientation = 'horizontal',
    this.onCellTap,
    this.onWallTap,
    this.enableRotation = false,
    this.isReplayMode = false,
    this.rotateBoard = false,
  });

  @override
  State<UnifiedBoardWidget> createState() => _UnifiedBoardWidgetState();
}

class _UnifiedBoardWidgetState extends State<UnifiedBoardWidget>
    with SingleTickerProviderStateMixin {
  late AnimationController _rotationController;
  late Animation<double> _rotationAnimation;
  int _previousTurn = 1;
  bool _isRotated = false;

  @override
  void initState() {
    super.initState();
    _rotationController = AnimationController(
      duration: const Duration(milliseconds: 600),
      vsync: this,
    );
    _rotationAnimation = Tween<double>(begin: 0, end: math.pi).animate(
      CurvedAnimation(parent: _rotationController, curve: Curves.easeInOut),
    );
    _previousTurn = widget.gameState.currentTurn;
    // Player 2 시작이면 이미 회전 상태로 시작
    if (widget.enableRotation && widget.gameState.currentTurn == 2) {
      _rotationController.value = 1.0;
      _isRotated = true;
    }
  }

  @override
  void didUpdateWidget(UnifiedBoardWidget oldWidget) {
    super.didUpdateWidget(oldWidget);

    // 회전 기능이 비활성화되면 원래 상태로 복귀
    if (!widget.enableRotation && _isRotated) {
      _rotationController.reverse();
      _isRotated = false;
    }

    // 회전 기능이 활성화되고 턴이 변경되면 회전
    if (widget.enableRotation && !widget.isReplayMode) {
      if (widget.gameState.currentTurn != _previousTurn) {
        if (widget.gameState.currentTurn == 2 && !_isRotated) {
          _rotationController.forward();
          _isRotated = true;
        } else if (widget.gameState.currentTurn == 1 && _isRotated) {
          _rotationController.reverse();
          _isRotated = false;
        }
        _previousTurn = widget.gameState.currentTurn;
      }
    }
  }

  @override
  void dispose() {
    _rotationController.dispose();
    super.dispose();
  }

  GameState get gameState => widget.gameState;
  List<Position> get validMoves => widget.validMoves;
  bool get wallMode => widget.wallMode;
  String get wallOrientation => widget.wallOrientation;
  Function(int row, int col)? get onCellTap => widget.onCellTap;
  Function(int row, int col, String orientation)? get onWallTap =>
      widget.onWallTap;

  // 벽 세그먼트 계산
  Set<String> get _horizontalWallSegments {
    final segments = <String>{};
    for (final wall in gameState.walls) {
      if (wall.orientation == 'horizontal') {
        segments.add('${wall.row},${wall.col}');
        segments.add('${wall.row},${wall.col + 1}');
      }
    }
    return segments;
  }

  Set<String> get _verticalWallSegments {
    final segments = <String>{};
    for (final wall in gameState.walls) {
      if (wall.orientation == 'vertical') {
        segments.add('${wall.row},${wall.col}');
        segments.add('${wall.row + 1},${wall.col}');
      }
    }
    return segments;
  }

  Set<String> get _wallCenters {
    return gameState.walls.map((w) => '${w.row},${w.col}').toSet();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return LayoutBuilder(
      builder: (context, outerConstraints) {
        // 화면 크기에 맞게 보드 크기 계산
        final availableWidth = outerConstraints.maxWidth;
        final availableHeight = outerConstraints.maxHeight.isFinite
            ? outerConstraints.maxHeight
            : MediaQuery.of(context).size.height * 0.5;

        // 최대 크기 제한 및 최소 크기 중 작은 값 사용
        const maxBoardSize = 500.0;
        final boardSize = <double>[availableWidth, availableHeight, maxBoardSize]
            .reduce((a, b) => a < b ? a : b);

        return Center(
          child: SizedBox(
            width: boardSize,
            height: boardSize,
            child: AnimatedBuilder(
              animation: _rotationAnimation,
              builder: (context, child) {
                // rotateBoard: 고정 180도 회전 (온라인 Player 2)
                // enableRotation: 턴마다 애니메이션 회전
                final double angle = widget.rotateBoard
                    ? math.pi
                    : (widget.enableRotation ? _rotationAnimation.value : 0.0);
                return Transform.rotate(
                  angle: angle,
                  child: child,
                );
              },
              child: Container(
                decoration: BoxDecoration(
                  color: colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(
                    color: Colors.brown.shade700,
                    width: 3,
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.1),
                      blurRadius: 10,
                      offset: const Offset(0, 4),
                    ),
                  ],
                ),
                padding: const EdgeInsets.all(8),
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    // 17x17 그리드 크기 계산
                    final totalSize = constraints.maxWidth;
                    final cellSize = totalSize / (9 * 5 + 8) * 5;
                    final gapSize = totalSize / (9 * 5 + 8);

                    return Column(
                      mainAxisSize: MainAxisSize.min,
                      children: List.generate(17, (gridRow) {
                        final isRowEven = gridRow % 2 == 0;
                        final rowHeight = isRowEven ? cellSize : gapSize;

                        return SizedBox(
                          height: rowHeight,
                          child: Row(
                            children: List.generate(17, (gridCol) {
                              final isColEven = gridCol % 2 == 0;
                              final colWidth = isColEven ? cellSize : gapSize;

                              return SizedBox(
                                width: colWidth,
                                height: rowHeight,
                                child: _buildGridItem(
                                  context,
                                  gridRow,
                                  gridCol,
                                  cellSize,
                                  gapSize,
                                ),
                              );
                            }),
                          ),
                        );
                      }),
                    );
                  },
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildGridItem(
    BuildContext context,
    int gridRow,
    int gridCol,
    double cellSize,
    double gapSize,
  ) {
    final isRowEven = gridRow % 2 == 0;
    final isColEven = gridCol % 2 == 0;

    if (isRowEven && isColEven) {
      // 셀 위치
      return _buildCell(context, gridRow ~/ 2, gridCol ~/ 2);
    } else if (isRowEven && !isColEven) {
      // 수직 벽 공간
      return _buildVerticalWallGap(context, gridRow ~/ 2, gridCol ~/ 2);
    } else if (!isRowEven && isColEven) {
      // 수평 벽 공간
      return _buildHorizontalWallGap(context, gridRow ~/ 2, gridCol ~/ 2);
    } else {
      // 교차점
      return _buildIntersection(context, gridRow ~/ 2, gridCol ~/ 2);
    }
  }

  Widget _buildCell(BuildContext context, int row, int col) {
    final colorScheme = Theme.of(context).colorScheme;
    final position = Position(row: row, col: col);

    final isPlayer1 = gameState.player1.position == position;
    final isPlayer2 = gameState.player2.position == position;
    final isValidMove = validMoves.contains(position) && !wallMode;
    final isGoalTop = row == 0;
    final isGoalBottom = row == 8;
    final isCurrentPlayerTurn = gameState.isPlayerTurn && !gameState.isFinished;

    // 배경색 결정
    Color backgroundColor;
    if (isValidMove && isCurrentPlayerTurn) {
      backgroundColor = Colors.green.shade200;
    } else if (isGoalTop) {
      backgroundColor = Colors.blue.shade50;
    } else if (isGoalBottom) {
      backgroundColor = Colors.red.shade50;
    } else {
      backgroundColor = Colors.amber.shade50;
    }

    // 테두리 색상
    Color borderColor = Colors.brown.shade200;
    if (isValidMove && isCurrentPlayerTurn) {
      borderColor = Colors.green.shade400;
    }

    return GestureDetector(
      key: Key('cell_${row}_$col'),
      onTap: isValidMove && isCurrentPlayerTurn && onCellTap != null
          ? () => onCellTap!(row, col)
          : null,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeInOut,
        margin: const EdgeInsets.all(1),
        decoration: BoxDecoration(
          color: backgroundColor,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: borderColor, width: 1),
          boxShadow: isValidMove && isCurrentPlayerTurn
              ? [
                  BoxShadow(
                    color: Colors.green.withOpacity(0.3),
                    blurRadius: 6,
                    spreadRadius: 1,
                  ),
                ]
              : null,
        ),
        child: Center(
          child: _buildCellContent(
            context,
            isPlayer1,
            isPlayer2,
            isValidMove && isCurrentPlayerTurn,
            isGoalTop,
            isGoalBottom,
          ),
        ),
      ),
    );
  }

  /// 현재 회전 각도
  double get _currentRotation {
    if (widget.rotateBoard) return math.pi;
    return widget.enableRotation ? _rotationAnimation.value : 0;
  }

  Widget _buildCellContent(
    BuildContext context,
    bool isPlayer1,
    bool isPlayer2,
    bool isValidMove,
    bool isGoalTop,
    bool isGoalBottom,
  ) {
    if (isPlayer1) {
      return AnimatedBuilder(
        animation: _rotationAnimation,
        builder: (context, _) {
          return _PlayerToken(
            color: Colors.blue,
            label: 'P1',
            isCurrentTurn: gameState.currentTurn == 1 && !gameState.isFinished,
            counterRotation: _currentRotation,
          );
        },
      );
    } else if (isPlayer2) {
      return AnimatedBuilder(
        animation: _rotationAnimation,
        builder: (context, _) {
          return _PlayerToken(
            color: Colors.red,
            label: gameState.isLocal2P ? 'P2' : 'AI',
            isCurrentTurn: gameState.currentTurn == 2 && !gameState.isFinished,
            counterRotation: _currentRotation,
          );
        },
      );
    } else if (isValidMove) {
      return Container(
        width: 12,
        height: 12,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Colors.green.shade600,
          boxShadow: [
            BoxShadow(
              color: Colors.green.withOpacity(0.4),
              blurRadius: 4,
            ),
          ],
        ),
      );
    } else if (isGoalTop) {
      // 회전 시 화살표도 역회전
      return AnimatedBuilder(
        animation: _rotationAnimation,
        builder: (context, _) {
          return Transform.rotate(
            angle: -_currentRotation,
            child: Icon(
              Icons.arrow_upward,
              size: 14,
              color: Colors.blue.shade300,
            ),
          );
        },
      );
    } else if (isGoalBottom) {
      // 회전 시 화살표도 역회전
      return AnimatedBuilder(
        animation: _rotationAnimation,
        builder: (context, _) {
          return Transform.rotate(
            angle: -_currentRotation,
            child: Icon(
              Icons.arrow_downward,
              size: 14,
              color: Colors.red.shade300,
            ),
          );
        },
      );
    }
    return const SizedBox.shrink();
  }

  Widget _buildVerticalWallGap(BuildContext context, int cellRow, int wallCol) {
    // 수직 벽 세그먼트 확인
    final hasWall = _verticalWallSegments.contains('$cellRow,$wallCol');
    final isCurrentPlayerTurn = gameState.isPlayerTurn && !gameState.isFinished;

    // 벽 설치 가능 위치 확인
    final canPlaceWall = wallMode &&
        wallOrientation == 'vertical' &&
        isCurrentPlayerTurn &&
        cellRow < 8 &&
        wallCol < 8 &&
        !_wallCenters.contains('$cellRow,$wallCol');

    if (hasWall) {
      return Container(
        margin: const EdgeInsets.symmetric(horizontal: 1, vertical: 2),
        decoration: BoxDecoration(
          color: Colors.brown.shade700,
          borderRadius: BorderRadius.circular(2),
        ),
      );
    } else if (canPlaceWall && onWallTap != null) {
      return GestureDetector(
        key: Key('wall_v_${cellRow}_$wallCol'),
        onTap: () => onWallTap!(cellRow, wallCol, 'vertical'),
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 1, vertical: 2),
          decoration: BoxDecoration(
            color: Colors.brown.shade200,
            borderRadius: BorderRadius.circular(2),
            border: Border.all(
              color: Colors.brown.shade400,
              width: 1,
            ),
          ),
          child: Center(
            child: Icon(
              Icons.more_vert,
              size: 10,
              color: Colors.brown.shade400,
            ),
          ),
        ),
      );
    }
    return const SizedBox.shrink();
  }

  Widget _buildHorizontalWallGap(
      BuildContext context, int wallRow, int cellCol) {
    // 수평 벽 세그먼트 확인
    final hasWall = _horizontalWallSegments.contains('$wallRow,$cellCol');
    final isCurrentPlayerTurn = gameState.isPlayerTurn && !gameState.isFinished;

    // 벽 설치 가능 위치 확인
    final canPlaceWall = wallMode &&
        wallOrientation == 'horizontal' &&
        isCurrentPlayerTurn &&
        wallRow < 8 &&
        cellCol < 8 &&
        !_wallCenters.contains('$wallRow,$cellCol');

    if (hasWall) {
      return Container(
        margin: const EdgeInsets.symmetric(horizontal: 2, vertical: 1),
        decoration: BoxDecoration(
          color: Colors.brown.shade700,
          borderRadius: BorderRadius.circular(2),
        ),
      );
    } else if (canPlaceWall && onWallTap != null) {
      return GestureDetector(
        key: Key('wall_h_${wallRow}_$cellCol'),
        onTap: () => onWallTap!(wallRow, cellCol, 'horizontal'),
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 2, vertical: 1),
          decoration: BoxDecoration(
            color: Colors.brown.shade200,
            borderRadius: BorderRadius.circular(2),
            border: Border.all(
              color: Colors.brown.shade400,
              width: 1,
            ),
          ),
          child: Center(
            child: Icon(
              Icons.horizontal_rule,
              size: 10,
              color: Colors.brown.shade400,
            ),
          ),
        ),
      );
    }
    return const SizedBox.shrink();
  }

  Widget _buildIntersection(BuildContext context, int intRow, int intCol) {
    // 교차점에 벽이 있는지 확인
    final hasHWall = gameState.walls.any(
        (w) => w.orientation == 'horizontal' && w.row == intRow && w.col == intCol);
    final hasVWall = gameState.walls.any(
        (w) => w.orientation == 'vertical' && w.row == intRow && w.col == intCol);

    if (hasHWall || hasVWall) {
      return Container(
        margin: const EdgeInsets.all(1),
        decoration: BoxDecoration(
          color: Colors.brown.shade700,
          borderRadius: BorderRadius.circular(2),
        ),
      );
    }
    return const SizedBox.shrink();
  }
}

/// 플레이어 토큰 위젯 (애니메이션 포함)
class _PlayerToken extends StatefulWidget {
  final Color color;
  final String label;
  final bool isCurrentTurn;
  final double counterRotation; // 보드 회전 시 텍스트 역회전 각도

  const _PlayerToken({
    required this.color,
    required this.label,
    required this.isCurrentTurn,
    this.counterRotation = 0,
  });

  @override
  State<_PlayerToken> createState() => _PlayerTokenState();
}

class _PlayerTokenState extends State<_PlayerToken>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _scaleAnimation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(milliseconds: 800),
      vsync: this,
    );
    _scaleAnimation = Tween<double>(begin: 1.0, end: 1.12).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );

    if (widget.isCurrentTurn) {
      _controller.repeat(reverse: true);
    }
  }

  @override
  void didUpdateWidget(_PlayerToken oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.isCurrentTurn && !_controller.isAnimating) {
      _controller.repeat(reverse: true);
    } else if (!widget.isCurrentTurn && _controller.isAnimating) {
      _controller.stop();
      _controller.reset();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _scaleAnimation,
      builder: (context, child) {
        return Transform.scale(
          scale: widget.isCurrentTurn ? _scaleAnimation.value : 1.0,
          child: Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: widget.color,
              boxShadow: [
                BoxShadow(
                  color: widget.color.withOpacity(0.4),
                  blurRadius: widget.isCurrentTurn ? 6 : 3,
                  spreadRadius: widget.isCurrentTurn ? 1 : 0,
                ),
              ],
            ),
            child: Center(
              // 텍스트 역회전으로 보드 회전 시에도 텍스트가 읽기 쉽게 유지
              child: Transform.rotate(
                angle: -widget.counterRotation,
                child: Text(
                  widget.label,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: 10,
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// 게임 정보 카드 위젯 (Material 3 스타일)
class GameInfoCard extends StatelessWidget {
  final GameState gameState;

  const GameInfoCard({super.key, required this.gameState});

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Card(
      elevation: 0,
      color: colorScheme.surfaceContainerLow,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _buildPlayerInfo(
              context,
              name: gameState.player1.name,
              walls: gameState.player1.wallsRemaining,
              isCurrentTurn: gameState.currentTurn == 1,
              color: Colors.blue,
            ),
            _buildStatusInfo(context),
            _buildPlayerInfo(
              context,
              name: gameState.player2.name,
              walls: gameState.player2.wallsRemaining,
              isCurrentTurn: gameState.currentTurn == 2,
              color: Colors.red,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPlayerInfo(
    BuildContext context, {
    required String name,
    required int walls,
    required bool isCurrentTurn,
    required Color color,
  }) {
    final colorScheme = Theme.of(context).colorScheme;

    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(3),
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: isCurrentTurn && !gameState.isFinished
                ? Border.all(color: Colors.green, width: 3)
                : null,
          ),
          child: CircleAvatar(
            backgroundColor: color,
            radius: 20,
            child: Text(
              name.isNotEmpty ? name[0].toUpperCase() : '?',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          name,
          style: TextStyle(
            fontWeight: isCurrentTurn ? FontWeight.bold : FontWeight.normal,
            color: colorScheme.onSurface,
          ),
        ),
        const SizedBox(height: 4),
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.fence, size: 14, color: Colors.brown.shade400),
            const SizedBox(width: 4),
            Text(
              '$walls',
              style: TextStyle(
                color: colorScheme.onSurfaceVariant,
                fontSize: 13,
              ),
            ),
          ],
        ),
        if (isCurrentTurn && !gameState.isFinished)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.green.shade100,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                '차례',
                style: TextStyle(
                  color: Colors.green.shade700,
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildStatusInfo(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    if (gameState.isFinished) {
      final winnerName = gameState.winner == 1
          ? gameState.player1.name
          : gameState.player2.name;
      final winnerColor = gameState.winner == 1 ? Colors.blue : Colors.red;

      return Column(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Colors.amber.shade100,
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.emoji_events,
              color: Colors.amber,
              size: 28,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '$winnerName 승리!',
            style: TextStyle(
              fontWeight: FontWeight.bold,
              color: winnerColor,
            ),
          ),
        ],
      );
    }

    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: colorScheme.primaryContainer,
            shape: BoxShape.circle,
          ),
          child: Text(
            '${gameState.turnCount}',
            style: TextStyle(
              fontWeight: FontWeight.bold,
              fontSize: 18,
              color: colorScheme.onPrimaryContainer,
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          '턴',
          style: TextStyle(
            color: colorScheme.onSurfaceVariant,
            fontSize: 13,
          ),
        ),
      ],
    );
  }
}
