import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'hub/hub_screen.dart';

void main() {
  // 플랫폼 로비 상태(인증/테마/프로필)와 개별 게임 로컬 상태는
  // Riverpod 으로 모듈별 분리한다 (PLATFORM_ARCHITECTURE.md §2.1).
  runApp(const ProviderScope(child: GamemoaApp()));
}

class GamemoaApp extends StatelessWidget {
  const GamemoaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '게임모아',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF3B5BDB)),
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF3B5BDB),
          brightness: Brightness.dark,
        ),
      ),
      home: const HubScreen(),
    );
  }
}
