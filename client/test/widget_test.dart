import 'package:flutter_test/flutter_test.dart';

import 'package:gamemoa/main.dart';
import 'package:gamemoa/hub/hub_screen.dart';

void main() {
  testWidgets('허브가 6종 게임 타일을 렌더링한다', (WidgetTester tester) async {
    await tester.pumpWidget(const GamemoaApp());

    expect(find.byType(HubScreen), findsOneWidget);
    expect(HubScreen.games.length, 6);
    for (final game in HubScreen.games) {
      expect(find.text(game.title), findsOneWidget);
    }
  });

  testWidgets('게임 모듈 id가 lib/games 디렉토리 이름과 일치한다', (WidgetTester tester) async {
    expect(HubScreen.games.map((g) => g.id).toList(), const [
      'maze_1p',
      'word_puzzle',
      'photo_jigsaw',
      'number_ten',
      'color_tile',
      'gomoku_renju',
    ]);
  });
}
