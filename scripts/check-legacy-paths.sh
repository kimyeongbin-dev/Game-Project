#!/usr/bin/env bash
# =============================================================================
# 레거시 경로 부활 차단
#
# 2026-09-30 구조 재편으로 아래 경로는 영구 폐기되었다.
#   backend_fastapi/  -> server/
#   frontend_flutter/ -> client/
#   games/            -> server/app/games/maze/
#
# 이 경로가 다시 추적되기 시작했다면 거의 확실히 머지 사고다.
# origin/develop, origin/dev-test 는 이 경로들에 파일을 가지고 있으므로,
# 해당 브랜치를 잘못 머지하면 구 구조가 되살아난다.
#
# 근본 차단은 `git merge -s ours` 로 ancestry 를 닫아 두었고(아래 참조),
# 이 스크립트는 그 조치가 무력화되는 경우를 잡는 안전망이다.
#
# 사용:
#   scripts/check-legacy-paths.sh          # 추적 중인 파일 검사 (CI / pre-commit)
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

LEGACY_PATHS=(backend_fastapi frontend_flutter games)

found="$(git ls-files -- "${LEGACY_PATHS[@]}" 2>/dev/null || true)"

if [ -n "$found" ]; then
  echo "FAIL: 폐기된 레거시 경로가 되살아났습니다 (머지 사고 가능성)"
  echo
  printf '%s\n' "$found" | head -20 | sed 's/^/  /'
  total="$(printf '%s\n' "$found" | wc -l | tr -d ' ')"
  [ "$total" -gt 20 ] && echo "  ... 외 $((total - 20))개"
  echo
  echo "조치:"
  echo "  1) 의도한 머지가 아니라면 되돌린다:  git merge --abort  또는  git reset --hard ORIG_HEAD"
  echo "  2) origin/develop 계열을 반영해야 한다면 내용만 가져온다:"
  echo "       git show origin/develop:<path> > <새 구조의 경로>"
  echo "  3) 구조 매핑은 PLATFORM_ARCHITECTURE.md §5 참조"
  exit 1
fi

echo "OK: 레거시 경로 없음 (${LEGACY_PATHS[*]})"
