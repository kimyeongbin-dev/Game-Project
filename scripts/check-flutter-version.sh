#!/usr/bin/env bash
# =============================================================================
# Flutter 버전 드리프트 검사
#
# 단일 기준: 저장소 루트 `.flutter-version`
# 검사 대상:
#   1) client/Dockerfile 의 ARG FLUTTER_VERSION 기본값   (불일치 → 실패)
#   2) 로컬에 설치된 Flutter SDK                         (불일치 → 실패, --warn 시 경고)
#
# 사용:
#   scripts/check-flutter-version.sh          # 전부 검사
#   scripts/check-flutter-version.sh --warn   # 로컬 불일치는 경고로만
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

WARN_ONLY=0
[ "${1:-}" = "--warn" ] && WARN_ONLY=1

expected="$(tr -d '[:space:]' < .flutter-version)"
if [ -z "$expected" ]; then
  echo "FAIL: .flutter-version 이 비어 있습니다"
  exit 1
fi
echo "기준 (.flutter-version): ${expected}"

status=0

# 1) Dockerfile 기본값
dockerfile_version="$(sed -n 's/^ARG FLUTTER_VERSION=\(.*\)$/\1/p' client/Dockerfile | head -1 | tr -d '[:space:]')"
if [ "$dockerfile_version" = "$expected" ]; then
  echo "  OK   client/Dockerfile ARG FLUTTER_VERSION=${dockerfile_version}"
else
  echo "  FAIL client/Dockerfile ARG FLUTTER_VERSION=${dockerfile_version:-<없음>} (기대: ${expected})"
  status=1
fi

# 2) 로컬 SDK
if command -v flutter >/dev/null 2>&1; then
  local_version="$(flutter --version 2>/dev/null | sed -n 's/^Flutter \([0-9][0-9.]*\).*/\1/p' | head -1)"
  if [ "$local_version" = "$expected" ]; then
    echo "  OK   로컬 Flutter ${local_version}"
  elif [ "$WARN_ONLY" = "1" ]; then
    echo "  WARN 로컬 Flutter ${local_version:-<확인 불가>} (기대: ${expected}) — 'flutter upgrade' 또는 해당 버전 설치 필요"
  else
    echo "  FAIL 로컬 Flutter ${local_version:-<확인 불가>} (기대: ${expected})"
    status=1
  fi
else
  echo "  SKIP flutter 명령을 찾을 수 없음 (컨테이너 전용 환경으로 판단)"
fi

exit $status
