import 'package:flutter/material.dart';
import '../models/game_state.dart';

/// 쿼리도 보드 위젯
class QuoridorBoardWidget extends StatelessWidget {
  final GameState gameState;
  final List<Position> validMoves;
  final bool wallMode;
  final String wallOrientation;
  final Function(int row, int col)? onCellTap;
  final Function(int row, int col, String orientation)? onWallTap;

  const QuoridorBoardWidget({
    super.key,
    required this.gameState,
    this.validMoves = const [],
    this.wallMode = false,
    this.wallOrientation = 'horizontal',
    this.onCellTap,
    this.onWallTap,
  });

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 1,
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: Colors.brown[100],
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.brown, width: 2),
        ),
        child: wallMode ? _buildWallGrid() : _buildBoardGrid(),
      ),
    );
  }

  Widget _buildBoardGrid() {
    final validPositions = validMoves.toSet();

    return GridView.builder(
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 9,
        crossAxisSpacing: 2,
        mainAxisSpacing: 2,
      ),
      itemCount: 81,
      itemBuilder: (context, index) {
        final row = index ~/ 9;
        final col = index % 9;
        final position = Position(row: row, col: col);

        final isPlayer1 = gameState.player1.position == position;
        final isPlayer2 = gameState.player2.position == position;
        final isValidMove = validPositions.contains(position);
        final isGoal = row == 0 || row == 8;

        return _buildCell(
          row: row,
          col: col,
          isPlayer1: isPlayer1,
          isPlayer2: isPlayer2,
          isValidMove: isValidMove,
          isGoal: isGoal,
        );
      },
    );
  }

  Widget _buildCell({
    required int row,
    required int col,
    required bool isPlayer1,
    required bool isPlayer2,
    required bool isValidMove,
    required bool isGoal,
  }) {
    Color backgroundColor = Colors.amber[50]!;

    if (isGoal) {
      backgroundColor = row == 0 ? Colors.blue[50]! : Colors.red[50]!;
    }
    if (isValidMove) {
      backgroundColor = Colors.green[200]!;
    }

    Widget? child;
    if (isPlayer1) {
      child = const CircleAvatar(
        backgroundColor: Colors.blue,
        child: Text('P1', style: TextStyle(color: Colors.white, fontSize: 10)),
      );
    } else if (isPlayer2) {
      child = const CircleAvatar(
        backgroundColor: Colors.red,
        child: Text('AI', style: TextStyle(color: Colors.white, fontSize: 10)),
      );
    } else if (isValidMove) {
      child = Container(
        width: 12,
        height: 12,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Colors.green[700],
        ),
      );
    }

    return GestureDetector(
      onTap: isValidMove && onCellTap != null
          ? () => onCellTap!(row, col)
          : null,
      child: Container(
        decoration: BoxDecoration(
          color: backgroundColor,
          border: Border.all(color: Colors.brown[300]!, width: 0.5),
          borderRadius: BorderRadius.circular(2),
        ),
        child: Center(child: child),
      ),
    );
  }

  Widget _buildWallGrid() {
    // 벽 설치 그리드 (8x8)
    return GridView.builder(
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 8,
        crossAxisSpacing: 4,
        mainAxisSpacing: 4,
      ),
      itemCount: 64,
      itemBuilder: (context, index) {
        final row = index ~/ 8;
        final col = index % 8;

        // 이미 설치된 벽 확인
        final hasWall = gameState.walls.any(
          (w) => w.row == row && w.col == col,
        );

        return GestureDetector(
          onTap: hasWall || onWallTap == null
              ? null
              : () => onWallTap!(row, col, wallOrientation),
          child: Container(
            decoration: BoxDecoration(
              color: hasWall ? Colors.brown[400] : Colors.amber[100],
              border: Border.all(
                color: hasWall ? Colors.brown : Colors.brown[300]!,
                width: hasWall ? 2 : 1,
              ),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Center(
              child: hasWall
                  ? const Icon(Icons.close, color: Colors.white, size: 16)
                  : Icon(
                      wallOrientation == 'horizontal'
                          ? Icons.horizontal_rule
                          : Icons.more_vert,
                      color: Colors.brown[300],
                      size: 16,
                    ),
            ),
          ),
        );
      },
    );
  }
}

/// 게임 정보 위젯
class GameInfoWidget extends StatelessWidget {
  final GameState gameState;

  const GameInfoWidget({super.key, required this.gameState});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _buildPlayerInfo(
              name: gameState.player1.name,
              walls: gameState.player1.wallsRemaining,
              isCurrentTurn: gameState.currentTurn == 1,
              color: Colors.blue,
            ),
            _buildStatusInfo(),
            _buildPlayerInfo(
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

  Widget _buildPlayerInfo({
    required String name,
    required int walls,
    required bool isCurrentTurn,
    required Color color,
  }) {
    return Column(
      children: [
        CircleAvatar(
          backgroundColor: color,
          child: Text(
            name[0].toUpperCase(),
            style: const TextStyle(color: Colors.white),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          name,
          style: TextStyle(
            fontWeight: isCurrentTurn ? FontWeight.bold : FontWeight.normal,
          ),
        ),
        Text('벽: $walls'),
        if (isCurrentTurn && !gameState.isFinished)
          const Text('◀ 턴', style: TextStyle(color: Colors.green)),
      ],
    );
  }

  Widget _buildStatusInfo() {
    if (gameState.isFinished) {
      final winnerName = gameState.winner == 1
          ? gameState.player1.name
          : gameState.player2.name;
      return Column(
        children: [
          const Icon(Icons.emoji_events, color: Colors.amber, size: 32),
          Text(
            '$winnerName 승리!',
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ],
      );
    }

    return Column(
      children: [
        Text('턴: ${gameState.turnCount}'),
        const SizedBox(height: 4),
        const Icon(Icons.sports_esports, size: 24),
      ],
    );
  }
}
