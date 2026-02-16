import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/game_state.dart';
import 'auth_service.dart';

/// 쿼리도 API 서비스
class QuoridorApiService {
  final String baseUrl;
  final http.Client _client;
  final AuthService? _authService;

  QuoridorApiService({
    String? baseUrl,
    http.Client? client,
    AuthService? authService,
  })  : baseUrl = baseUrl ?? 'http://${AuthService.serverHost}/api/v1/quoridor',
        _client = client ?? http.Client(),
        _authService = authService;

  Map<String, String> _buildHeaders({bool json = false}) {
    final headers = <String, String>{};
    if (json) {
      headers['Content-Type'] = 'application/json';
    }
    final token = _authService?.token;
    if (token != null && token.isNotEmpty) {
      headers['Authorization'] = 'Bearer $token';
    }
    return headers;
  }

  /// 새 게임 생성
  Future<Map<String, dynamic>> createGame({
    String player1Name = 'Player 1',
    String player2Name = 'Player 2',
    String aiDifficulty = 'normal',
    String gameMode = 'vs_ai',
  }) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/games'),
      headers: _buildHeaders(json: true),
      body: jsonEncode({
        'player1_name': player1Name,
        'player2_name': player2Name,
        'ai_difficulty': aiDifficulty,
        'game_mode': gameMode,
      }),
    );

    if (response.statusCode == 201) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw ApiException('Failed to create game: ${response.statusCode}');
  }

  /// 게임 상태 조회
  Future<GameState> getGame(String gameId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/games/$gameId'),
      headers: _buildHeaders(),
    );

    if (response.statusCode == 200) {
      return GameState.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to get game: ${response.statusCode}');
  }

  /// 폰 이동
  Future<ActionResponse> movePawn(String gameId, int row, int col) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/games/$gameId/move'),
      headers: _buildHeaders(json: true),
      body: jsonEncode({'row': row, 'col': col}),
    );

    if (response.statusCode == 200) {
      return ActionResponse.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to move pawn: ${response.statusCode}');
  }

  /// 벽 설치
  Future<ActionResponse> placeWall(
    String gameId,
    int row,
    int col,
    String orientation,
  ) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/games/$gameId/wall'),
      headers: _buildHeaders(json: true),
      body: jsonEncode({
        'row': row,
        'col': col,
        'orientation': orientation,
      }),
    );

    if (response.statusCode == 200) {
      return ActionResponse.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to place wall: ${response.statusCode}');
  }

  /// AI 턴 요청
  Future<AIActionResponse> aiMove(String gameId) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/games/$gameId/ai-move'),
      headers: _buildHeaders(),
    );

    if (response.statusCode == 200) {
      return AIActionResponse.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to get AI move: ${response.statusCode}');
  }

  /// 유효한 이동 목록 조회
  Future<ValidMoves> getValidMoves(String gameId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/games/$gameId/valid-moves'),
      headers: _buildHeaders(),
    );

    if (response.statusCode == 200) {
      return ValidMoves.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to get valid moves: ${response.statusCode}');
  }

  /// 진행 중인 게임 세션 목록 조회 (DB 연동)
  Future<ActiveSessionsResponse> getActiveSessions({int limit = 50}) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/sessions?limit=$limit'),
      headers: _buildHeaders(),
    );

    if (response.statusCode == 200) {
      return ActiveSessionsResponse.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to get active sessions: ${response.statusCode}');
  }

  /// DB에서 게임 복구 (서버 재시작 후 세션 복구용)
  Future<GameState> recoverGame(String gameId) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/games/$gameId/recover'),
      headers: _buildHeaders(),
    );

    if (response.statusCode == 200) {
      return GameState.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to recover game: ${response.statusCode}');
  }

  /// 게임 히스토리 조회 (리플레이용)
  Future<GameHistoryResponse> getGameHistory(String gameId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/games/$gameId/history'),
      headers: _buildHeaders(),
    );

    if (response.statusCode == 200) {
      return GameHistoryResponse.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to get game history: ${response.statusCode}');
  }

  /// 게임 상태 동기화 (앱 시작 시 또는 게임 진입 시)
  /// 서버에서 최신 게임 상태를 가져옵니다.
  Future<GameState?> syncGameState(String gameId) async {
    try {
      // 먼저 일반 조회 시도 (메모리에서 조회)
      return await getGame(gameId);
    } on ApiException catch (e) {
      if (e.message.contains('404')) {
        // 메모리에 없으면 DB에서 복구 시도
        try {
          return await recoverGame(gameId);
        } catch (_) {
          return null;
        }
      }
      rethrow;
    }
  }

  /// 게임 포기 (기록 보존, 활성 목록에서만 제외)
  Future<bool> abandonGame(String gameId) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/games/$gameId/abandon'),
      headers: _buildHeaders(),
    );

    return response.statusCode == 204;
  }

  /// 게임 완전 삭제 (기록도 숨김)
  Future<bool> deleteGame(String gameId) async {
    final response = await _client.delete(
      Uri.parse('$baseUrl/games/$gameId'),
      headers: _buildHeaders(),
    );

    return response.statusCode == 204;
  }

  // ===== 리플레이 시스템 API =====

  /// 리플레이용 수 목록 조회 (GameMove 테이블)
  Future<ReplayMovesResponse> getReplayMoves(String gameId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/games/$gameId/replay/moves'),
    );

    if (response.statusCode == 200) {
      return ReplayMovesResponse.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to get replay moves: ${response.statusCode}');
  }

  /// 특정 스텝의 게임 상태 조회
  Future<ReplayStateResponse> getReplayState(String gameId, int stepNo) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/games/$gameId/replay/state/$stepNo'),
    );

    if (response.statusCode == 200) {
      return ReplayStateResponse.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }
    throw ApiException('Failed to get replay state: ${response.statusCode}');
  }

  /// 게임 총 수 개수 조회
  Future<int> getTotalMoves(String gameId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/games/$gameId/replay/total'),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['total_moves'] as int;
    }
    throw ApiException('Failed to get total moves: ${response.statusCode}');
  }

  void dispose() {
    _client.close();
  }
}

class ActionResponse {
  final bool success;
  final GameState? gameState;
  final String message;
  final String? error;

  const ActionResponse({
    required this.success,
    this.gameState,
    required this.message,
    this.error,
  });

  factory ActionResponse.fromJson(Map<String, dynamic> json) {
    return ActionResponse(
      success: json['success'] as bool,
      gameState: json['game_state'] != null
          ? GameState.fromJson(json['game_state'] as Map<String, dynamic>)
          : null,
      message: json['message'] as String,
      error: json['error'] as String?,
    );
  }
}

class AIActionResponse {
  final bool success;
  final AIAction? action;
  final GameState? gameState;
  final String message;

  const AIActionResponse({
    required this.success,
    this.action,
    this.gameState,
    required this.message,
  });

  factory AIActionResponse.fromJson(Map<String, dynamic> json) {
    return AIActionResponse(
      success: json['success'] as bool,
      action: json['action'] != null
          ? AIAction.fromJson(json['action'] as Map<String, dynamic>)
          : null,
      gameState: json['game_state'] != null
          ? GameState.fromJson(json['game_state'] as Map<String, dynamic>)
          : null,
      message: json['message'] as String,
    );
  }
}

class ApiException implements Exception {
  final String message;
  const ApiException(this.message);

  @override
  String toString() => 'ApiException: $message';
}

/// 세션 정보
class SessionInfo {
  final String gameId;
  final String player1Name;
  final String player2Name;
  final String gameMode;
  final int currentTurn;
  final int turnCount;
  final String createdAt;
  final String updatedAt;

  const SessionInfo({
    required this.gameId,
    required this.player1Name,
    required this.player2Name,
    required this.gameMode,
    required this.currentTurn,
    required this.turnCount,
    required this.createdAt,
    required this.updatedAt,
  });

  factory SessionInfo.fromJson(Map<String, dynamic> json) {
    return SessionInfo(
      gameId: json['game_id'] as String,
      player1Name: json['player1_name'] as String,
      player2Name: json['player2_name'] as String,
      gameMode: json['game_mode'] as String,
      currentTurn: json['current_turn'] as int,
      turnCount: json['turn_count'] as int,
      createdAt: json['created_at'] as String,
      updatedAt: json['updated_at'] as String,
    );
  }
}

/// 진행 중인 세션 목록 응답
class ActiveSessionsResponse {
  final List<SessionInfo> sessions;
  final int count;

  const ActiveSessionsResponse({
    required this.sessions,
    required this.count,
  });

  factory ActiveSessionsResponse.fromJson(Map<String, dynamic> json) {
    return ActiveSessionsResponse(
      sessions: (json['sessions'] as List)
          .map((s) => SessionInfo.fromJson(s as Map<String, dynamic>))
          .toList(),
      count: json['count'] as int,
    );
  }
}

/// 게임 히스토리 항목
class HistoryEntry {
  final int turn;
  final int player;
  final Map<String, dynamic> action;
  final String timestamp;

  const HistoryEntry({
    required this.turn,
    required this.player,
    required this.action,
    required this.timestamp,
  });

  factory HistoryEntry.fromJson(Map<String, dynamic> json) {
    return HistoryEntry(
      turn: json['turn'] as int,
      player: json['player'] as int,
      action: json['action'] as Map<String, dynamic>,
      timestamp: json['timestamp'] as String,
    );
  }
}

/// 게임 히스토리 응답 (리플레이용)
class GameHistoryResponse {
  final String gameId;
  final List<HistoryEntry> history;
  final int totalMoves;

  const GameHistoryResponse({
    required this.gameId,
    required this.history,
    required this.totalMoves,
  });

  factory GameHistoryResponse.fromJson(Map<String, dynamic> json) {
    return GameHistoryResponse(
      gameId: json['game_id'] as String,
      history: (json['history'] as List)
          .map((h) => HistoryEntry.fromJson(h as Map<String, dynamic>))
          .toList(),
      totalMoves: json['total_moves'] as int,
    );
  }
}

// ===== 리플레이 시스템 모델 =====

/// 수 기록 (GameMove 테이블 기반)
class MoveRecord {
  final int stepNo;
  final int player;
  final String actionType;
  final int row;
  final int col;
  final String? orientation;
  final String createdAt;

  const MoveRecord({
    required this.stepNo,
    required this.player,
    required this.actionType,
    required this.row,
    required this.col,
    this.orientation,
    required this.createdAt,
  });

  factory MoveRecord.fromJson(Map<String, dynamic> json) {
    return MoveRecord(
      stepNo: json['step_no'] as int,
      player: json['player'] as int,
      actionType: json['action_type'] as String,
      row: json['row'] as int,
      col: json['col'] as int,
      orientation: json['orientation'] as String?,
      createdAt: json['created_at'] as String,
    );
  }
}

/// 리플레이 수 목록 응답
class ReplayMovesResponse {
  final String gameId;
  final List<MoveRecord> moves;
  final int totalMoves;

  const ReplayMovesResponse({
    required this.gameId,
    required this.moves,
    required this.totalMoves,
  });

  factory ReplayMovesResponse.fromJson(Map<String, dynamic> json) {
    return ReplayMovesResponse(
      gameId: json['game_id'] as String,
      moves: (json['moves'] as List)
          .map((m) => MoveRecord.fromJson(m as Map<String, dynamic>))
          .toList(),
      totalMoves: json['total_moves'] as int,
    );
  }
}

/// 리플레이 특정 스텝 상태 응답
class ReplayStateResponse {
  final String gameId;
  final int stepNo;
  final Map<String, dynamic> gameState;
  final bool isInitial;

  const ReplayStateResponse({
    required this.gameId,
    required this.stepNo,
    required this.gameState,
    required this.isInitial,
  });

  factory ReplayStateResponse.fromJson(Map<String, dynamic> json) {
    return ReplayStateResponse(
      gameId: json['game_id'] as String,
      stepNo: json['step_no'] as int,
      gameState: json['game_state'] as Map<String, dynamic>,
      isInitial: json['is_initial'] as bool? ?? false,
    );
  }
}
