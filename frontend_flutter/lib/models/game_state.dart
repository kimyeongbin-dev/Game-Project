// 쿼리도 게임 상태 모델

class Position {
  final int row;
  final int col;

  const Position({required this.row, required this.col});

  factory Position.fromJson(Map<String, dynamic> json) {
    return Position(
      row: json['row'] as int,
      col: json['col'] as int,
    );
  }

  Map<String, dynamic> toJson() => {'row': row, 'col': col};

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Position &&
          runtimeType == other.runtimeType &&
          row == other.row &&
          col == other.col;

  @override
  int get hashCode => row.hashCode ^ col.hashCode;
}

class Wall {
  final int row;
  final int col;
  final String orientation;

  const Wall({
    required this.row,
    required this.col,
    required this.orientation,
  });

  factory Wall.fromJson(Map<String, dynamic> json) {
    return Wall(
      row: json['row'] as int,
      col: json['col'] as int,
      orientation: json['orientation'] as String,
    );
  }

  Map<String, dynamic> toJson() => {
        'row': row,
        'col': col,
        'orientation': orientation,
      };
}

class Player {
  final String name;
  final Position position;
  final int wallsRemaining;
  final int goalRow;

  const Player({
    required this.name,
    required this.position,
    required this.wallsRemaining,
    required this.goalRow,
  });

  factory Player.fromJson(Map<String, dynamic> json) {
    return Player(
      name: json['name'] as String,
      position: Position.fromJson(json['position'] as Map<String, dynamic>),
      wallsRemaining: json['walls_remaining'] as int,
      goalRow: json['goal_row'] as int,
    );
  }
}

class GameState {
  final String gameId;
  final String status;
  /// 서버 game_mode 값 (vs_ai, ranked, friend_match)
  final String gameMode;
  final int currentTurn;
  final int turnCount;
  final Player player1;
  final Player player2;
  final List<Wall> walls;
  final int? winner;
  final String createdAt;
  final String updatedAt;

  const GameState({
    required this.gameId,
    required this.status,
    required this.gameMode,
    required this.currentTurn,
    required this.turnCount,
    required this.player1,
    required this.player2,
    required this.walls,
    this.winner,
    required this.createdAt,
    required this.updatedAt,
  });

  factory GameState.fromJson(Map<String, dynamic> json) {
    final players = json['players'] as Map<String, dynamic>;
    final wallsJson = json['walls'] as List<dynamic>? ?? const [];
    return GameState(
      gameId: json['game_id'] as String,
      status: json['status'] as String,
      gameMode: json['game_mode'] as String? ?? 'vs_ai',
      currentTurn: json['current_turn'] as int,
      turnCount: json['turn_count'] as int,
      player1: Player.fromJson(players['player1'] as Map<String, dynamic>),
      player2: Player.fromJson(players['player2'] as Map<String, dynamic>),
      walls: wallsJson
          .map((w) => Wall.fromJson(w as Map<String, dynamic>))
          .toList(),
      winner: json['winner'] as int?,
      createdAt: json['created_at'] as String,
      updatedAt: json['updated_at'] as String,
    );
  }

  // 하위 호환성: 'finished'도 종료 상태로 처리
  bool get isFinished => status == 'player1_win' || status == 'player2_win' || status == 'finished';
  bool get isPlayer1Win => status == 'player1_win' || (status == 'finished' && winner == 1);
  bool get isPlayer2Win => status == 'player2_win' || (status == 'finished' && winner == 2);
  bool get isVsAI => gameMode == 'vs_ai';
  bool get isRanked => gameMode == 'ranked';
  bool get isFriendMatch => gameMode == 'friend_match';

  /// 현재 로컬 기기에서 조작 가능한지 여부
  /// - vs_ai: Player 1만 조작 가능
  /// - ranked/friend_match: 온라인 모드는 별도 로직에서 제어
  bool get isPlayerTurn => isVsAI && currentTurn == 1;

  Player get currentPlayer => currentTurn == 1 ? player1 : player2;
}

class ValidMoves {
  final List<Position> pawnMoves;
  final List<Wall> wallPlacements;
  final int wallsRemaining;

  const ValidMoves({
    required this.pawnMoves,
    required this.wallPlacements,
    required this.wallsRemaining,
  });

  factory ValidMoves.fromJson(Map<String, dynamic> json) {
    final pawnMovesJson = json['valid_pawn_moves'] as List<dynamic>? ?? const [];
    final wallPlacementsJson = json['valid_wall_placements'] as List<dynamic>? ?? const [];
    return ValidMoves(
      pawnMoves: pawnMovesJson
          .map((p) => Position.fromJson(p as Map<String, dynamic>))
          .toList(),
      wallPlacements: wallPlacementsJson
          .map((w) => Wall.fromJson(w as Map<String, dynamic>))
          .toList(),
      wallsRemaining: json['walls_remaining'] as int? ?? 0,
    );
  }
}

class AIAction {
  final String type;
  final int row;
  final int col;
  final String? orientation;

  const AIAction({
    required this.type,
    required this.row,
    required this.col,
    this.orientation,
  });

  factory AIAction.fromJson(Map<String, dynamic> json) {
    return AIAction(
      type: json['type'] as String,
      row: json['row'] as int,
      col: json['col'] as int,
      orientation: json['orientation'] as String?,
    );
  }
}
