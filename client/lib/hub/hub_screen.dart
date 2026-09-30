import 'package:flutter/material.dart';

/// 플랫폼 로비 골격.
///
/// 벤토(Bento) 그리드 UI, 카카오 로그인, 전적, 퍼즐 편지 진입은
/// API 설계서 확정 후 구현한다 (PLATFORM_ARCHITECTURE.md §5 `hub/`).
class HubScreen extends StatelessWidget {
  const HubScreen({super.key});

  /// 문서 §4 게임 라인업. 모듈 경로는 `lib/games/<id>/` 와 일치한다.
  static const List<({String id, String title, String subtitle})> games = [
    (id: 'maze_1p', title: '1인칭 미로 대결', subtitle: '시야 제한 · 1:1 / 1:1:1'),
    (id: 'word_puzzle', title: '낱말 퍼즐', subtitle: '다중 테마 크로스워드'),
    (id: 'photo_jigsaw', title: '퍼즐 맞추기', subtitle: '커스텀 사진 · 시크릿 편지'),
    (id: 'number_ten', title: '합 10 퍼즐', subtitle: '드래그 제거 · 역산 보드'),
    (id: 'color_tile', title: '컬러 타일', subtitle: '교차점 제거 퍼즐'),
    (id: 'gomoku_renju', title: '오목', subtitle: '렌주룰 금수 판정'),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('게임모아')),
      body: LayoutBuilder(
        builder: (context, constraints) {
          final columns = constraints.maxWidth >= 720 ? 3 : 2;
          return GridView.count(
            padding: const EdgeInsets.all(16),
            crossAxisCount: columns,
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            children: [
              for (final game in games)
                _GameTile(title: game.title, subtitle: game.subtitle),
            ],
          );
        },
      ),
    );
  }
}

class _GameTile extends StatelessWidget {
  const _GameTile({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(subtitle, style: theme.textTheme.bodySmall),
            const Spacer(),
            Text('준비 중', style: theme.textTheme.labelSmall),
          ],
        ),
      ),
    );
  }
}
