import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// WebSocket 연결 상태
enum WsConnectionState {
  disconnected,
  connecting,
  connected,
  error,
}

/// 매칭 상태
enum MatchingState {
  idle,           // 대기 중
  inQueue,        // 큐에서 매칭 대기 중
  inRoom,         // 친구 대전 방에서 대기 중
  matched,        // 매칭 완료
  inGame,         // 게임 진행 중
}

/// WebSocket 메시지 타입
class WsMessageType {
  // 클라이언트 → 서버
  static const String joinQueue = 'join_queue';
  static const String leaveQueue = 'leave_queue';
  static const String createRoom = 'create_room';
  static const String joinRoom = 'join_room';
  static const String leaveRoom = 'leave_room';
  static const String ready = 'ready';
  static const String move = 'move';
  static const String wall = 'wall';
  static const String surrender = 'surrender';

  // 서버 → 클라이언트
  static const String connected = 'connected';
  static const String queueJoined = 'queue_joined';
  static const String queueLeft = 'queue_left';
  static const String queueStatus = 'queue_status';
  static const String matchFound = 'match_found';
  static const String roomCreated = 'room_created';
  static const String roomJoined = 'room_joined';
  static const String roomLeft = 'room_left';
  static const String playerJoined = 'player_joined';
  static const String playerLeft = 'player_left';
  static const String playerReady = 'player_ready';
  static const String gameStart = 'game_start';
  static const String gameState = 'game_state';
  static const String gameEnd = 'game_end';
  static const String opponentDisconnected = 'opponent_disconnected';
  static const String opponentReconnected = 'opponent_reconnected';
  static const String error = 'error';
}

/// WebSocket 메시지
class WsMessage {
  final String type;
  final Map<String, dynamic> data;

  const WsMessage({required this.type, this.data = const {}});

  factory WsMessage.fromJson(Map<String, dynamic> json) {
    return WsMessage(
      type: json['type'] as String,
      data: Map<String, dynamic>.from(json)..remove('type'),
    );
  }

  Map<String, dynamic> toJson() => {'type': type, ...data};

  String toJsonString() => jsonEncode(toJson());
}

/// 매칭 정보
class MatchInfo {
  final String gameId;
  final int playerNumber;  // 1 또는 2
  final String opponentNickname;
  final double? opponentScore;
  final bool isRanked;
  final String? roomCode;
  final Map<String, dynamic>? initialGameState;  // 초기 게임 상태

  const MatchInfo({
    required this.gameId,
    required this.playerNumber,
    required this.opponentNickname,
    this.opponentScore,
    required this.isRanked,
    this.roomCode,
    this.initialGameState,
  });

  factory MatchInfo.fromJson(Map<String, dynamic> json) {
    // 서버에서 보내는 형식: you_are_player, player1_nickname, player2_nickname
    final playerNum = json['you_are_player'] as int? ?? json['player_number'] as int? ?? 1;

    // 상대방 닉네임 결정
    String opponentNick;
    if (json['opponent_nickname'] != null) {
      opponentNick = json['opponent_nickname'] as String;
    } else if (json['opponent'] != null) {
      opponentNick = json['opponent'] as String;
    } else if (playerNum == 1) {
      opponentNick = json['player2_nickname'] as String? ?? 'Unknown';
    } else {
      opponentNick = json['player1_nickname'] as String? ?? 'Unknown';
    }

    // is_ranked 또는 game_mode로 판단
    final isRankedGame = json['is_ranked'] as bool? ??
        (json['game_mode'] == 'ranked');

    return MatchInfo(
      gameId: json['game_id'] as String,
      playerNumber: playerNum,
      opponentNickname: opponentNick,
      opponentScore: (json['opponent_score'] as num?)?.toDouble(),
      isRanked: isRankedGame,
      roomCode: json['room_code'] as String?,
      initialGameState: json['game_state'] as Map<String, dynamic>?,
    );
  }
}

/// 게임 종료 정보
class GameEndInfo {
  final int winner;
  final String reason;
  final double? scoreChange;
  final int? newRank;
  final int turnCount;

  const GameEndInfo({
    required this.winner,
    required this.reason,
    this.scoreChange,
    this.newRank,
    required this.turnCount,
  });

  factory GameEndInfo.fromJson(Map<String, dynamic> json) {
    // turn_count는 final_state 안에 있을 수 있음
    int turnCount = json['turn_count'] as int? ?? 0;
    if (turnCount == 0 && json['final_state'] != null) {
      final finalState = json['final_state'] as Map<String, dynamic>;
      turnCount = finalState['turn_count'] as int? ?? 0;
    }

    return GameEndInfo(
      winner: json['winner'] as int,
      reason: json['reason'] as String? ?? 'unknown',
      scoreChange: (json['score_change'] as num?)?.toDouble(),
      newRank: json['new_rank'] as int?,
      turnCount: turnCount,
    );
  }
}

/// WebSocket 게임 서비스
class WebSocketService extends ChangeNotifier {
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;

  WsConnectionState _connectionState = WsConnectionState.disconnected;
  MatchingState _matchingState = MatchingState.idle;
  String? _lastError;

  // 현재 게임/매칭 정보
  MatchInfo? _currentMatch;
  String? _roomCode;
  int _queuePosition = 0;

  // 콜백들
  final List<void Function(WsMessage)> _messageListeners = [];
  void Function(Map<String, dynamic>)? onGameStateUpdate;
  void Function(GameEndInfo)? onGameEnd;
  void Function(MatchInfo)? onMatchFound;
  void Function(String)? onError;
  void Function()? onOpponentDisconnected;
  void Function()? onOpponentReconnected;

  // Getters
  WsConnectionState get connectionState => _connectionState;
  MatchingState get matchingState => _matchingState;
  bool get isConnected => _connectionState == WsConnectionState.connected;
  bool get isInGame => _matchingState == MatchingState.inGame;
  String? get lastError => _lastError;
  MatchInfo? get currentMatch => _currentMatch;
  String? get roomCode => _roomCode;
  int get queuePosition => _queuePosition;

  /// WebSocket 연결
  Future<bool> connect(String serverUrl, String token) async {
    if (_connectionState == WsConnectionState.connected) {
      return true;
    }

    _connectionState = WsConnectionState.connecting;
    _lastError = null;
    notifyListeners();

    try {
      // WebSocket URL 구성
      final wsUrl = serverUrl
          .replaceFirst('http://', 'ws://')
          .replaceFirst('https://', 'wss://');
      final uri = Uri.parse('$wsUrl/ws/game?token=$token');

      _channel = WebSocketChannel.connect(uri);

      // 연결 대기
      await _channel!.ready;

      _connectionState = WsConnectionState.connected;
      _matchingState = MatchingState.idle;
      notifyListeners();

      // 메시지 리스너 설정
      _subscription = _channel!.stream.listen(
        _handleMessage,
        onError: _handleError,
        onDone: _handleDisconnect,
      );

      return true;
    } catch (e) {
      _lastError = '연결 실패: $e';
      _connectionState = WsConnectionState.error;
      notifyListeners();
      return false;
    }
  }

  /// 연결 해제
  void disconnect() {
    debugPrint('[WebSocket] disconnect() called');
    debugPrint('[WebSocket] Stack trace: ${StackTrace.current}');
    _subscription?.cancel();
    _channel?.sink.close();
    _channel = null;
    _connectionState = WsConnectionState.disconnected;
    _matchingState = MatchingState.idle;
    _currentMatch = null;
    _roomCode = null;
    notifyListeners();
  }

  /// 메시지 전송
  void send(WsMessage message) {
    if (_channel == null || _connectionState != WsConnectionState.connected) {
      _lastError = '연결되지 않음';
      debugPrint('[WebSocket] 전송 실패 - 연결되지 않음: ${message.type}');
      return;
    }
    debugPrint('[WebSocket] 전송: ${message.type}');
    _channel!.sink.add(message.toJsonString());
  }

  // ==================== 랭킹전 ====================

  /// 랭킹전 큐 참가
  void joinQueue() {
    send(const WsMessage(type: WsMessageType.joinQueue));
  }

  /// 랭킹전 큐 나가기
  void leaveQueue() {
    send(const WsMessage(type: WsMessageType.leaveQueue));
  }

  // ==================== 친구 대전 ====================

  /// 방 생성
  void createRoom() {
    send(const WsMessage(type: WsMessageType.createRoom));
  }

  /// 방 참가
  void joinRoom(String roomCode) {
    send(WsMessage(
      type: WsMessageType.joinRoom,
      data: {'room_code': roomCode},
    ));
  }

  /// 방 나가기
  void leaveRoom() {
    send(const WsMessage(type: WsMessageType.leaveRoom));
  }

  /// 준비 완료 (친구대전)
  void setReady() {
    send(const WsMessage(type: WsMessageType.ready));
  }

  // ==================== 게임 액션 ====================

  /// 폰 이동
  void movePawn(int row, int col) {
    send(WsMessage(
      type: 'move',  // 서버가 기대하는 타입
      data: {
        'row': row,
        'col': col,
      },
    ));
  }

  /// 벽 설치
  void placeWall(int row, int col, String orientation) {
    send(WsMessage(
      type: 'wall',  // 서버가 기대하는 타입
      data: {
        'row': row,
        'col': col,
        'orientation': orientation,
      },
    ));
  }

  /// 항복
  void surrender() {
    send(const WsMessage(type: WsMessageType.surrender));
  }

  // ==================== 메시지 핸들러 ====================

  void _handleMessage(dynamic rawMessage) {
    try {
      final json = jsonDecode(rawMessage as String) as Map<String, dynamic>;
      final message = WsMessage.fromJson(json);

      debugPrint('[WebSocket] 수신: ${message.type}');

      // 전체 리스너에게 알림
      for (final listener in _messageListeners) {
        listener(message);
      }

      // 타입별 처리
      switch (message.type) {
        case WsMessageType.connected:
          _connectionState = WsConnectionState.connected;
          break;

        case WsMessageType.queueJoined:
          _matchingState = MatchingState.inQueue;
          _queuePosition = message.data['position'] as int? ?? 0;
          break;

        case WsMessageType.queueLeft:
          _matchingState = MatchingState.idle;
          _queuePosition = 0;
          break;

        case WsMessageType.matchFound:
          _currentMatch = MatchInfo.fromJson(message.data);
          _matchingState = MatchingState.matched;
          onMatchFound?.call(_currentMatch!);
          break;

        case WsMessageType.roomCreated:
          _roomCode = message.data['room_code'] as String;
          _matchingState = MatchingState.inRoom;
          break;

        case WsMessageType.roomJoined:
          _roomCode = message.data['room_code'] as String;
          _matchingState = MatchingState.inRoom;
          break;

        case WsMessageType.playerJoined:
          // 상대방 입장, 곧 게임 시작됨
          break;

        case WsMessageType.gameStart:
          _currentMatch = MatchInfo.fromJson(message.data);
          _matchingState = MatchingState.inGame;
          onMatchFound?.call(_currentMatch!);
          // game_state가 포함되어 있으면 게임 상태도 업데이트
          if (message.data['game_state'] != null) {
            onGameStateUpdate?.call(message.data['game_state'] as Map<String, dynamic>);
          }
          break;

        case WsMessageType.gameState:
          _matchingState = MatchingState.inGame;
          // 서버는 {"type": "game_state", "game_state": {...}, ...} 형태로 보냄
          final gameStateData = message.data['game_state'] as Map<String, dynamic>?;
          if (gameStateData != null) {
            onGameStateUpdate?.call(gameStateData);
          }
          break;

        case WsMessageType.gameEnd:
          final endInfo = GameEndInfo.fromJson(message.data);
          onGameEnd?.call(endInfo);
          _matchingState = MatchingState.idle;
          _currentMatch = null;
          break;

        case WsMessageType.opponentDisconnected:
          onOpponentDisconnected?.call();
          break;

        case WsMessageType.opponentReconnected:
          onOpponentReconnected?.call();
          break;

        case WsMessageType.error:
          _lastError = message.data['message'] as String? ?? 'Unknown error';
          onError?.call(_lastError!);
          break;
      }

      notifyListeners();
    } catch (e) {
      debugPrint('WebSocket message parse error: $e');
    }
  }

  void _handleError(dynamic error) {
    _lastError = error.toString();
    _connectionState = WsConnectionState.error;
    onError?.call(_lastError!);
    notifyListeners();
  }

  void _handleDisconnect() {
    debugPrint('[WebSocket] _handleDisconnect() called - connection closed by server or network');
    _connectionState = WsConnectionState.disconnected;
    _matchingState = MatchingState.idle;
    _currentMatch = null;
    notifyListeners();
  }

  /// 메시지 리스너 추가
  void addMessageListener(void Function(WsMessage) listener) {
    _messageListeners.add(listener);
  }

  /// 메시지 리스너 제거
  void removeMessageListener(void Function(WsMessage) listener) {
    _messageListeners.remove(listener);
  }

  @override
  void dispose() {
    debugPrint('[WebSocket] dispose() called');
    debugPrint('[WebSocket] Stack trace: ${StackTrace.current}');
    disconnect();
    _messageListeners.clear();
    super.dispose();
  }
}
