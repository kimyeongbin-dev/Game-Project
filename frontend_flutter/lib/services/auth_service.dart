import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// 유저 정보 모델
class UserInfo {
  final int userId;
  final String nickname;
  final String sessionToken;
  final double score;
  final int wins;
  final int losses;
  final int? bestTurnCount;
  final int? rank;
  final bool isChampion;

  const UserInfo({
    required this.userId,
    required this.nickname,
    required this.sessionToken,
    this.score = 0,
    this.wins = 0,
    this.losses = 0,
    this.bestTurnCount,
    this.rank,
    this.isChampion = false,
  });

  factory UserInfo.fromLoginResponse(Map<String, dynamic> json) {
    return UserInfo(
      userId: json['user_id'] as int,
      nickname: json['nickname'] as String,
      sessionToken: json['session_token'] as String,
      score: (json['score'] as num?)?.toDouble() ?? 0,
      wins: json['wins'] as int? ?? 0,
      losses: json['losses'] as int? ?? 0,
      bestTurnCount: json['best_turn_count'] as int?,
    );
  }

  factory UserInfo.fromMeResponse(Map<String, dynamic> json, String token) {
    return UserInfo(
      userId: json['user_id'] as int,
      nickname: json['nickname'] as String,
      sessionToken: token,
      score: (json['score'] as num?)?.toDouble() ?? 0,
      wins: json['wins'] as int? ?? 0,
      losses: json['losses'] as int? ?? 0,
      bestTurnCount: json['best_turn_count'] as int?,
      rank: json['rank'] as int?,
      isChampion: json['is_champion'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() => {
    'user_id': userId,
    'nickname': nickname,
    'session_token': sessionToken,
    'score': score,
    'wins': wins,
    'losses': losses,
    'best_turn_count': bestTurnCount,
    'rank': rank,
    'is_champion': isChampion,
  };

  factory UserInfo.fromJson(Map<String, dynamic> json) {
    return UserInfo(
      userId: json['user_id'] as int,
      nickname: json['nickname'] as String,
      sessionToken: json['session_token'] as String,
      score: (json['score'] as num?)?.toDouble() ?? 0,
      wins: json['wins'] as int? ?? 0,
      losses: json['losses'] as int? ?? 0,
      bestTurnCount: json['best_turn_count'] as int?,
      rank: json['rank'] as int?,
      isChampion: json['is_champion'] as bool? ?? false,
    );
  }

  UserInfo copyWith({
    int? userId,
    String? nickname,
    String? sessionToken,
    double? score,
    int? wins,
    int? losses,
    int? bestTurnCount,
    int? rank,
    bool? isChampion,
  }) {
    return UserInfo(
      userId: userId ?? this.userId,
      nickname: nickname ?? this.nickname,
      sessionToken: sessionToken ?? this.sessionToken,
      score: score ?? this.score,
      wins: wins ?? this.wins,
      losses: losses ?? this.losses,
      bestTurnCount: bestTurnCount ?? this.bestTurnCount,
      rank: rank ?? this.rank,
      isChampion: isChampion ?? this.isChampion,
    );
  }
}

/// 리셋 시간 정보
class ResetTimeInfo {
  final String nextResetAt;
  final String timeRemaining;
  final int resetHourKst;

  const ResetTimeInfo({
    required this.nextResetAt,
    required this.timeRemaining,
    required this.resetHourKst,
  });

  factory ResetTimeInfo.fromJson(Map<String, dynamic> json) {
    return ResetTimeInfo(
      nextResetAt: json['next_reset_at'] as String,
      timeRemaining: json['time_remaining'] as String,
      resetHourKst: json['reset_hour_kst'] as int,
    );
  }
}

/// 인증 결과
class AuthResult {
  final bool success;
  final UserInfo? user;
  final String message;
  final String? error;
  final ResetTimeInfo? resetInfo;

  const AuthResult({
    required this.success,
    this.user,
    required this.message,
    this.error,
    this.resetInfo,
  });

  factory AuthResult.fromJson(Map<String, dynamic> json) {
    UserInfo? user;
    if (json['success'] == true && json['session_token'] != null) {
      user = UserInfo.fromLoginResponse(json);
    }

    ResetTimeInfo? resetInfo;
    if (json['reset_info'] != null) {
      resetInfo = ResetTimeInfo.fromJson(json['reset_info'] as Map<String, dynamic>);
    }

    return AuthResult(
      success: json['success'] as bool,
      user: user,
      message: json['message'] as String? ?? '',
      error: json['error'] as String?,
      resetInfo: resetInfo,
    );
  }
}

/// 인증 서비스 (ChangeNotifier로 상태 관리)
class AuthService extends ChangeNotifier {
  static const String _tokenKey = 'session_token';
  static const String _userKey = 'user_info';

  final String baseUrl;
  final http.Client _client;

  UserInfo? _currentUser;
  bool _isLoading = false;
  String? _lastError;

  AuthService({
    String? baseUrl,
    http.Client? client,
  })  : baseUrl = baseUrl ?? _getDefaultBaseUrl(),
        _client = client ?? http.Client();

  // 서버 IP 설정 (같은 네트워크에서 테스트 시 노트북 IP로 변경)
  static const String serverHost = '192.168.0.16:8000';  // 네트워크 테스트용
  // static const String serverHost = 'localhost:8000';  // 로컬 테스트용

  static String _getDefaultBaseUrl() {
    return 'http://$serverHost/api/v1/users';
  }

  // Getters
  UserInfo? get currentUser => _currentUser;
  bool get isLoggedIn => _currentUser != null;
  bool get isLoading => _isLoading;
  String? get lastError => _lastError;
  String? get token => _currentUser?.sessionToken;

  /// 서버 URL 변경 (다른 서버 연결용)
  String getServerUrl() => baseUrl.replaceAll('/api/v1/users', '');

  /// 저장된 토큰으로 자동 로그인 시도
  Future<bool> tryAutoLogin() async {
    _isLoading = true;
    notifyListeners();

    try {
      final prefs = await SharedPreferences.getInstance();
      final savedToken = prefs.getString(_tokenKey);
      final savedUserJson = prefs.getString(_userKey);

      if (savedToken == null) {
        _isLoading = false;
        notifyListeners();
        return false;
      }

      // 저장된 유저 정보가 있으면 먼저 복원
      if (savedUserJson != null) {
        try {
          _currentUser = UserInfo.fromJson(jsonDecode(savedUserJson));
        } catch (_) {
          // 파싱 실패 시 무시
        }
      }

      // 서버에서 최신 정보 가져오기
      final result = await getMyInfo(savedToken);
      if (result != null) {
        _currentUser = result;
        await _saveUserLocally();
        _isLoading = false;
        notifyListeners();
        return true;
      } else {
        // 토큰 만료됨
        await _clearLocalData();
        _currentUser = null;
        _isLoading = false;
        notifyListeners();
        return false;
      }
    } catch (e) {
      _lastError = e.toString();
      _isLoading = false;
      notifyListeners();
      return false;
    }
  }

  /// 회원가입
  Future<AuthResult> register(String nickname, String password) async {
    _isLoading = true;
    _lastError = null;
    notifyListeners();

    try {
      final response = await _client.post(
        Uri.parse('$baseUrl/register'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'nickname': nickname,
          'password': password,
        }),
      );

      final json = jsonDecode(response.body) as Map<String, dynamic>;
      final result = AuthResult.fromJson(json);

      if (result.success && result.user != null) {
        _currentUser = result.user;
        await _saveUserLocally();
      } else {
        _lastError = result.error ?? result.message;
      }

      _isLoading = false;
      notifyListeners();
      return result;
    } catch (e) {
      _lastError = '서버 연결 실패: $e';
      _isLoading = false;
      notifyListeners();
      return AuthResult(
        success: false,
        message: _lastError!,
        error: 'connection_error',
      );
    }
  }

  /// 로그인
  Future<AuthResult> login(String nickname, String password) async {
    _isLoading = true;
    _lastError = null;
    notifyListeners();

    try {
      final response = await _client.post(
        Uri.parse('$baseUrl/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'nickname': nickname,
          'password': password,
        }),
      );

      final json = jsonDecode(response.body) as Map<String, dynamic>;
      final result = AuthResult.fromJson(json);

      if (result.success && result.user != null) {
        _currentUser = result.user;
        await _saveUserLocally();
      } else {
        _lastError = result.error ?? result.message;
      }

      _isLoading = false;
      notifyListeners();
      return result;
    } catch (e) {
      _lastError = '서버 연결 실패: $e';
      _isLoading = false;
      notifyListeners();
      return AuthResult(
        success: false,
        message: _lastError!,
        error: 'connection_error',
      );
    }
  }

  /// 로그아웃
  Future<bool> logout() async {
    if (_currentUser == null) return true;

    _isLoading = true;
    notifyListeners();

    try {
      await _client.post(
        Uri.parse('$baseUrl/logout'),
        headers: _authHeaders(),
      );
    } catch (_) {
      // 서버 에러는 무시하고 로컬은 정리
    }

    await _clearLocalData();
    _currentUser = null;
    _isLoading = false;
    notifyListeners();
    return true;
  }

  /// 내 정보 조회
  Future<UserInfo?> getMyInfo([String? tokenOverride]) async {
    final useToken = tokenOverride ?? _currentUser?.sessionToken;
    if (useToken == null) return null;

    try {
      final response = await _client.get(
        Uri.parse('$baseUrl/me'),
        headers: {'Authorization': 'Bearer $useToken'},
      );

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        return UserInfo.fromMeResponse(json, useToken);
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  /// 정보 새로고침
  Future<bool> refreshUserInfo() async {
    if (_currentUser == null) return false;

    final updated = await getMyInfo();
    if (updated != null) {
      _currentUser = updated;
      await _saveUserLocally();
      notifyListeners();
      return true;
    }
    return false;
  }

  /// 닉네임 사용 가능 여부 확인
  Future<({bool available, String message})> checkNickname(String nickname) async {
    try {
      final response = await _client.get(
        Uri.parse('$baseUrl/check-nickname/$nickname'),
      );

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        return (
          available: json['available'] as bool,
          message: json['message'] as String,
        );
      }
      return (available: false, message: '서버 오류');
    } catch (e) {
      return (available: false, message: '서버 연결 실패');
    }
  }

  /// Heartbeat (30초마다 호출 권장)
  Future<bool> heartbeat() async {
    if (_currentUser == null) return false;

    try {
      final response = await _client.post(
        Uri.parse('$baseUrl/heartbeat'),
        headers: _authHeaders(),
      );
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// 인증 헤더 생성
  Map<String, String> _authHeaders() {
    return {
      'Content-Type': 'application/json',
      if (_currentUser != null)
        'Authorization': 'Bearer ${_currentUser!.sessionToken}',
    };
  }

  /// Authorization 헤더만 반환 (WebSocket 등에서 사용)
  Map<String, String> get authHeader {
    if (_currentUser == null) return {};
    return {'Authorization': 'Bearer ${_currentUser!.sessionToken}'};
  }

  /// 로컬에 유저 정보 저장
  Future<void> _saveUserLocally() async {
    if (_currentUser == null) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, _currentUser!.sessionToken);
    await prefs.setString(_userKey, jsonEncode(_currentUser!.toJson()));
  }

  /// 로컬 데이터 삭제
  Future<void> _clearLocalData() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    await prefs.remove(_userKey);
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }
}
