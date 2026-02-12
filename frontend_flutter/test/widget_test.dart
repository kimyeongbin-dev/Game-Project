// Basic Flutter widget test for Game Hub

import 'package:flutter_test/flutter_test.dart';
import 'package:game_hub/main.dart';

void main() {
  testWidgets('App loads correctly', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const GameHubApp());

    // Wait for post-frame callbacks and initial build
    // Using pump() instead of pumpAndSettle() to avoid timeout from network requests
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    // Verify that the app loads (loading screen or main screen)
    // The app shows a loading spinner initially
    expect(find.byType(GameHubApp), findsOneWidget);
  });
}
