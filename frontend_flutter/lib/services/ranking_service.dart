import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// 리더보드 항목
class LeaderboardEntry {
  final int rank;
  final String nickname;
  final double score;
  final int wins;
  final int losses;
  final int? bestTurnCount;
  final bool isChampion;

  const LeaderboardEntry({
    required this.rank,
    required this.nickname,
    required this.score,
    required this.wins,
    required this.losses,
    this.bestTurnCount,
    this.isChampion = false,
  });

  factory LeaderboardEntry.fromJson(Map<String, dynamic> json) {
    return LeaderboardEntry(
      rank: json['rank'] as int,
      nickname: json['nickname'] as String,
      score: (json['score'] as num).toDouble(),
      wins: json['wins'] as int,
      losses: json['losses'] as int,
      bestTurnCount: json['best_turn_count'] as int?,
      isChampion: json['is_champion'] as bool? ?? false,
    );
  }

  double get winRate {
    final total = wins + losses;
    if (total == 0) return 0;
    return wins / total * 100;
  }
}

/// 일일 챔피언
class DailyChampion {
  final String date;
  final String nickname;
  final double score;
  final int wins;
  final int losses;
  final int? bestTurnCount;

  const DailyChampion({
    required this.date,
    required this.nickname,
    required this.score,
    required this.wins,
    required this.losses,
    this.bestTurnCount,
  });

  factory DailyChampion.fromJson(Map<String, dynamic> json) {
    return DailyChampion(
      date: json['date'] as String,
      nickname: json['nickname'] as String,
      score: (json['score'] as num).toDouble(),
      wins: json['wins'] as int,
      losses: json['losses'] as int,
      bestTurnCount: json['best_turn_count'] as int?,
    );
  }
}

/// 리더보드 응답
class LeaderboardResponse {
  final List<LeaderboardEntry> entries;
  final int totalPlayers;
  final DailyChampion? yesterdayChampion;
  final String? nextResetAt;
  final String? timeRemaining;

  const LeaderboardResponse({
    required this.entries,
    required this.totalPlayers,
    this.yesterdayChampion,
    this.nextResetAt,
    this.timeRemaining,
  });

  factory LeaderboardResponse.fromJson(Map<String, dynamic> json) {
    DailyChampion? champion;
    if (json['yesterday_champion'] != null) {
      champion = DailyChampion.fromJson(
        json['yesterday_champion'] as Map<String, dynamic>,
      );
    }

    String? nextReset;
    String? remaining;
    if (json['reset_info'] != null) {
      final resetInfo = json['reset_info'] as Map<String, dynamic>;
      nextReset = resetInfo['next_reset_at'] as String?;
      remaining = resetInfo['time_remaining'] as String?;
    }

    return LeaderboardResponse(
      entries: (json['entries'] as List)
          .map((e) => LeaderboardEntry.fromJson(e as Map<String, dynamic>))
          .toList(),
      totalPlayers: json['total_players'] as int,
      yesterdayChampion: champion,
      nextResetAt: nextReset,
      timeRemaining: remaining,
    );
  }
}

/// 내 랭킹 정보
class MyRankInfo {
  final int rank;
  final String nickname;
  final double score;
  final int wins;
  final int losses;
  final int? bestTurnCount;
  final int totalPlayers;

  const MyRankInfo({
    required this.rank,
    required this.nickname,
    required this.score,
    required this.wins,
    required this.losses,
    this.bestTurnCount,
    required this.totalPlayers,
  });

  factory MyRankInfo.fromJson(Map<String, dynamic> json) {
    return MyRankInfo(
      rank: json['rank'] as int,
      nickname: json['nickname'] as String,
      score: (json['score'] as num).toDouble(),
      wins: json['wins'] as int,
      losses: json['losses'] as int,
      bestTurnCount: json['best_turn_count'] as int?,
      totalPlayers: json['total_players'] as int,
    );
  }

  double get winRate {
    final total = wins + losses;
    if (total == 0) return 0;
    return wins / total * 100;
  }

  String get percentile {
    if (totalPlayers == 0) return '-';
    final pct = (rank / totalPlayers * 100).toStringAsFixed(1);
    return 'Top $pct%';
  }
}

/// 랭킹 서비스
class RankingService {
  final String baseUrl;
  final http.Client _client;
  String? _authToken;

  RankingService({
    String? baseUrl,
    http.Client? client,
  })  : baseUrl = baseUrl ?? _getDefaultBaseUrl(),
        _client = client ?? http.Client();

  static String _getDefaultBaseUrl() {
    // AuthService와 동일한 서버 호스트 사용
    return 'http://192.168.0.16:8000/api/v1/ranking';
  }

  /// 인증 토큰 설정
  void setAuthToken(String? token) {
    _authToken = token;
  }

  Map<String, String> get _headers {
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (_authToken != null) {
      headers['Authorization'] = 'Bearer $_authToken';
    }
    return headers;
  }

  /// 리더보드 조회
  Future<LeaderboardResponse?> getLeaderboard({int limit = 20}) async {
    try {
      final response = await _client.get(
        Uri.parse('$baseUrl/leaderboard?limit=$limit'),
        headers: _headers,
      );

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        return LeaderboardResponse.fromJson(json);
      }
      return null;
    } catch (e) {
      debugPrint('Failed to get leaderboard: $e');
      return null;
    }
  }

  /// 내 순위 조회
  Future<MyRankInfo?> getMyRank() async {
    if (_authToken == null) return null;

    try {
      final response = await _client.get(
        Uri.parse('$baseUrl/my-rank'),
        headers: _headers,
      );

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        return MyRankInfo.fromJson(json);
      }
      return null;
    } catch (e) {
      debugPrint('Failed to get my rank: $e');
      return null;
    }
  }

  /// 전날 챔피언 조회
  Future<DailyChampion?> getYesterdayChampion() async {
    try {
      final response = await _client.get(
        Uri.parse('$baseUrl/champion'),
        headers: _headers,
      );

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        if (json['success'] == true && json['champion'] != null) {
          return DailyChampion.fromJson(json['champion'] as Map<String, dynamic>);
        }
      }
      return null;
    } catch (e) {
      debugPrint('Failed to get champion: $e');
      return null;
    }
  }

  /// 최근 챔피언 목록 조회
  Future<List<DailyChampion>> getRecentChampions({int days = 7}) async {
    try {
      final response = await _client.get(
        Uri.parse('$baseUrl/champions?days=$days'),
        headers: _headers,
      );

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        final champions = json['champions'] as List;
        return champions
            .map((c) => DailyChampion.fromJson(c as Map<String, dynamic>))
            .toList();
      }
      return [];
    } catch (e) {
      debugPrint('Failed to get recent champions: $e');
      return [];
    }
  }

  void dispose() {
    _client.close();
  }
}
