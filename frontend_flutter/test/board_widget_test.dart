// 쿼리도 보드 위젯 테스트
// 실제 셀 클릭, 이동, 상태 변경 테스트

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:game_hub/models/game_state.dart';
import 'package:game_hub/widgets/unified_board_widget.dart';

void main() {
  group('GameState Model Tests', () {
    test('초기 게임 상태 생성', () {
      final gameState = _createInitialGameState();

      expect(gameState.currentTurn, 1);
      expect(gameState.turnCount, 0);
      expect(gameState.status, 'in_progress');
      expect(gameState.player1.position.row, 8);
      expect(gameState.player1.position.col, 4);
      expect(gameState.player2.position.row, 0);
      expect(gameState.player2.position.col, 4);
    });

    test('Player1 앞으로 이동 후 상태', () {
      // Player1이 (8,4) -> (7,4)로 이동한 상태
      final gameState = _createGameStateAfterMove(
        player1Row: 7,
        player1Col: 4,
        currentTurn: 2,
        turnCount: 1,
      );

      expect(gameState.player1.position.row, 7);
      expect(gameState.currentTurn, 2);
      expect(gameState.turnCount, 1);
    });

    test('Player2 앞으로 이동 후 상태', () {
      // Player2가 (0,4) -> (1,4)로 이동한 상태
      final gameState = _createGameStateAfterMove(
        player1Row: 7,
        player1Col: 4,
        player2Row: 1,
        player2Col: 4,
        currentTurn: 1,
        turnCount: 2,
      );

      expect(gameState.player2.position.row, 1);
      expect(gameState.currentTurn, 1);
      expect(gameState.turnCount, 2);
    });
  });

  group('UnifiedBoardWidget 셀 클릭 테스트', () {
    testWidgets('보드 위젯 렌더링 및 셀 Key 확인', (WidgetTester tester) async {
      final gameState = _createInitialGameState();

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: UnifiedBoardWidget(
              gameState: gameState,
              validMoves: const [
                Position(row: 7, col: 4), // 앞으로
              ],
            ),
          ),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 보드가 렌더링되었는지 확인
      expect(find.byType(UnifiedBoardWidget), findsOneWidget);

      // 셀 Key가 존재하는지 확인
      expect(find.byKey(const Key('cell_7_4')), findsOneWidget);
      expect(find.byKey(const Key('cell_8_4')), findsOneWidget);
      expect(find.byKey(const Key('cell_0_0')), findsOneWidget);
    });

    testWidgets('유효한 셀 클릭 시 콜백 호출', (WidgetTester tester) async {
      final gameState = _createInitialGameState();
      int? tappedRow;
      int? tappedCol;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: UnifiedBoardWidget(
              gameState: gameState,
              validMoves: const [
                Position(row: 7, col: 4), // 이동 가능 위치
              ],
              onCellTap: (row, col) {
                tappedRow = row;
                tappedCol = col;
              },
            ),
          ),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 유효한 이동 위치 (7, 4) 셀 클릭
      await tester.tap(find.byKey(const Key('cell_7_4')));
      await tester.pump();

      // 콜백이 올바른 좌표로 호출되었는지 확인
      expect(tappedRow, 7);
      expect(tappedCol, 4);
    });

    testWidgets('유효하지 않은 셀 클릭 시 콜백 미호출', (WidgetTester tester) async {
      final gameState = _createInitialGameState();
      bool callbackCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: UnifiedBoardWidget(
              gameState: gameState,
              validMoves: const [
                Position(row: 7, col: 4), // (7,4)만 유효
              ],
              onCellTap: (row, col) {
                callbackCalled = true;
              },
            ),
          ),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 유효하지 않은 위치 (5, 5) 셀 클릭
      await tester.tap(find.byKey(const Key('cell_5_5')));
      await tester.pump();

      // 콜백이 호출되지 않아야 함
      expect(callbackCalled, false);
    });

    testWidgets('Player1 셀 클릭으로 이동 후 상태 변경', (WidgetTester tester) async {
      var gameState = _createInitialGameState();
      int? lastTappedRow;
      int? lastTappedCol;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: StatefulBuilder(
              builder: (context, setState) {
                return Column(
                  children: [
                    // 게임 정보 표시
                    Text('Turn: ${gameState.currentTurn}'),
                    Text('P1: (${gameState.player1.position.row}, ${gameState.player1.position.col})'),
                    Text('Turn Count: ${gameState.turnCount}'),

                    // 보드 위젯
                    Expanded(
                      child: UnifiedBoardWidget(
                        gameState: gameState,
                        validMoves: gameState.currentTurn == 1
                            ? const [Position(row: 7, col: 4)]
                            : const [],
                        onCellTap: (row, col) {
                          lastTappedRow = row;
                          lastTappedCol = col;
                          // Player1이 (7,4)로 이동하면 상태 업데이트
                          if (gameState.currentTurn == 1 && row == 7 && col == 4) {
                            setState(() {
                              gameState = _createGameStateAfterMove(
                                player1Row: 7,
                                player1Col: 4,
                                currentTurn: 2,
                                turnCount: 1,
                              );
                            });
                          }
                        },
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 초기 상태 확인
      expect(find.text('Turn: 1'), findsOneWidget);
      expect(find.text('P1: (8, 4)'), findsOneWidget);
      expect(find.text('Turn Count: 0'), findsOneWidget);

      // (7, 4) 셀 클릭 - Player1 앞으로 이동
      await tester.tap(find.byKey(const Key('cell_7_4')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 이동 후 상태 확인
      expect(lastTappedRow, 7);
      expect(lastTappedCol, 4);
      expect(find.text('Turn: 2'), findsOneWidget);
      expect(find.text('P1: (7, 4)'), findsOneWidget);
      expect(find.text('Turn Count: 1'), findsOneWidget);
    });

    testWidgets('양쪽 플레이어 교대로 셀 클릭 이동', (WidgetTester tester) async {
      var gameState = _createInitialGameState();

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: StatefulBuilder(
              builder: (context, setState) {
                // 현재 턴에 따른 유효 이동 위치 계산
                List<Position> validMoves;
                if (gameState.currentTurn == 1) {
                  // Player1: 현재 위치에서 위로 한 칸
                  validMoves = [
                    Position(
                      row: gameState.player1.position.row - 1,
                      col: gameState.player1.position.col,
                    ),
                  ];
                } else {
                  // Player2: 현재 위치에서 아래로 한 칸
                  validMoves = [
                    Position(
                      row: gameState.player2.position.row + 1,
                      col: gameState.player2.position.col,
                    ),
                  ];
                }

                return Column(
                  children: [
                    Text('Current Turn: ${gameState.currentTurn}'),
                    Text('P1 Position: (${gameState.player1.position.row}, ${gameState.player1.position.col})'),
                    Text('P2 Position: (${gameState.player2.position.row}, ${gameState.player2.position.col})'),
                    Text('Total Turns: ${gameState.turnCount}'),

                    Expanded(
                      child: UnifiedBoardWidget(
                        gameState: gameState,
                        validMoves: validMoves,
                        onCellTap: (row, col) {
                          setState(() {
                            if (gameState.currentTurn == 1) {
                              // Player1 이동
                              gameState = _createGameStateAfterMove(
                                player1Row: row,
                                player1Col: col,
                                player2Row: gameState.player2.position.row,
                                player2Col: gameState.player2.position.col,
                                currentTurn: 2,
                                turnCount: gameState.turnCount + 1,
                              );
                            } else {
                              // Player2 이동
                              gameState = _createGameStateAfterMove(
                                player1Row: gameState.player1.position.row,
                                player1Col: gameState.player1.position.col,
                                player2Row: row,
                                player2Col: col,
                                currentTurn: 1,
                                turnCount: gameState.turnCount + 1,
                              );
                            }
                          });
                        },
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 초기 상태
      expect(find.text('Current Turn: 1'), findsOneWidget);
      expect(find.text('P1 Position: (8, 4)'), findsOneWidget);
      expect(find.text('P2 Position: (0, 4)'), findsOneWidget);

      // Player 1 이동: (8,4) -> (7,4) 셀 클릭
      await tester.tap(find.byKey(const Key('cell_7_4')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('Current Turn: 2'), findsOneWidget);
      expect(find.text('P1 Position: (7, 4)'), findsOneWidget);
      expect(find.text('Total Turns: 1'), findsOneWidget);

      // Player 2 이동: (0,4) -> (1,4) 셀 클릭
      await tester.tap(find.byKey(const Key('cell_1_4')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('Current Turn: 1'), findsOneWidget);
      expect(find.text('P2 Position: (1, 4)'), findsOneWidget);
      expect(find.text('Total Turns: 2'), findsOneWidget);

      // Player 1 다시 이동: (7,4) -> (6,4) 셀 클릭
      await tester.tap(find.byKey(const Key('cell_6_4')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('Current Turn: 2'), findsOneWidget);
      expect(find.text('P1 Position: (6, 4)'), findsOneWidget);
      expect(find.text('Total Turns: 3'), findsOneWidget);
    });

    testWidgets('벽 모드에서 셀 클릭 시 이동 비활성화', (WidgetTester tester) async {
      final gameState = _createInitialGameState();
      bool cellTapCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: UnifiedBoardWidget(
              gameState: gameState,
              validMoves: const [Position(row: 7, col: 4)],
              wallMode: true, // 벽 모드 활성화
              onCellTap: (row, col) {
                cellTapCalled = true;
              },
            ),
          ),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 벽 모드에서 셀 클릭
      await tester.tap(find.byKey(const Key('cell_7_4')));
      await tester.pump();

      // 벽 모드에서는 셀 탭 콜백이 호출되지 않아야 함
      expect(cellTapCalled, false);
    });
  });

  group('Game Flow Tests', () {
    testWidgets('게임 승리 조건 테스트 - Player1 골인', (WidgetTester tester) async {
      // Player1이 골인 직전 상태 (row 1)
      var gameState = _createGameStateAfterMove(
        player1Row: 1,
        player1Col: 4,
        currentTurn: 1,
        turnCount: 14,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: StatefulBuilder(
              builder: (context, setState) {
                return Column(
                  children: [
                    Text('Status: ${gameState.status}'),
                    Text('Winner: ${gameState.winner ?? "none"}'),
                    Text('P1 at row: ${gameState.player1.position.row}'),

                    Expanded(
                      child: UnifiedBoardWidget(
                        gameState: gameState,
                        validMoves: gameState.status == 'in_progress'
                            ? const [Position(row: 0, col: 4)]
                            : const [],
                        onCellTap: (row, col) {
                          if (row == 0) {
                            // Player1이 row 0에 도달 -> 승리
                            setState(() {
                              gameState = _createWinState(winner: 1);
                            });
                          }
                        },
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 게임 진행 중
      expect(find.text('Status: in_progress'), findsOneWidget);
      expect(find.text('Winner: none'), findsOneWidget);

      // Player1 골인 셀 (0, 4) 클릭
      await tester.tap(find.byKey(const Key('cell_0_4')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 승리 확인
      expect(find.text('Status: player1_win'), findsOneWidget);
      expect(find.text('Winner: 1'), findsOneWidget);
    });
  });
}

// ========== Helper Functions ==========

/// 초기 게임 상태 생성
GameState _createInitialGameState() {
  return const GameState(
    gameId: 'test-game-001',
    status: 'in_progress',
    gameMode: 'local_2p',
    currentTurn: 1,
    turnCount: 0,
    player1: Player(
      name: 'Player1',
      position: Position(row: 8, col: 4),
      wallsRemaining: 10,
      goalRow: 0,
    ),
    player2: Player(
      name: 'Player2',
      position: Position(row: 0, col: 4),
      wallsRemaining: 10,
      goalRow: 8,
    ),
    walls: [],
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
  );
}

/// 이동 후 게임 상태 생성
GameState _createGameStateAfterMove({
  int player1Row = 8,
  int player1Col = 4,
  int player2Row = 0,
  int player2Col = 4,
  required int currentTurn,
  required int turnCount,
}) {
  return GameState(
    gameId: 'test-game-001',
    status: 'in_progress',
    gameMode: 'local_2p',
    currentTurn: currentTurn,
    turnCount: turnCount,
    player1: Player(
      name: 'Player1',
      position: Position(row: player1Row, col: player1Col),
      wallsRemaining: 10,
      goalRow: 0,
    ),
    player2: Player(
      name: 'Player2',
      position: Position(row: player2Row, col: player2Col),
      wallsRemaining: 10,
      goalRow: 8,
    ),
    walls: const [],
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:01Z',
  );
}

/// 승리 상태 생성
GameState _createWinState({required int winner}) {
  return GameState(
    gameId: 'test-game-001',
    status: winner == 1 ? 'player1_win' : 'player2_win',
    gameMode: 'local_2p',
    currentTurn: winner,
    turnCount: 15,
    player1: Player(
      name: 'Player1',
      position: Position(row: winner == 1 ? 0 : 2, col: 4),
      wallsRemaining: 8,
      goalRow: 0,
    ),
    player2: Player(
      name: 'Player2',
      position: Position(row: winner == 2 ? 8 : 6, col: 4),
      wallsRemaining: 8,
      goalRow: 8,
    ),
    walls: const [],
    winner: winner,
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:01:00Z',
  );
}
