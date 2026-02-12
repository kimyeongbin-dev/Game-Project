// Basic Flutter widget test for Game Hub

import 'package:flutter_test/flutter_test.dart';
import 'package:game_hub/main.dart';

void main() {
  testWidgets('App loads correctly', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const GameHubApp());

    // Wait for the app to initialize
    await tester.pumpAndSettle();

    // Verify that the app title is present
    expect(find.text('Game Hub'), findsWidgets);
  });
}
