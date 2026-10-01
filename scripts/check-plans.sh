#!/usr/bin/env bash
# =============================================================================
# 이관되지 않은 계획서 감지
#
# 플랜 모드는 계획서를 하니스 디렉토리(`~/.claude/plans/`)에 만든다. 저장소 밖이고
# 무작위 이름이라, 그 자리에 두면 새 세션이 존재를 모르고 컨텍스트를 비우면
# 계획의 근거·제외 범위를 추적할 수 없다.
#
# 실제로 초판 API 설계서 계획이 이렇게 소실됐다 — 개정 계획을 같은 파일에
# 덮어썼고, 옮겨두지 않아 원본이 사라졌다.
#
# 규약은 docs/plans/README.md 에 있다. 이 스크립트는 그 규약이 지켜지지 않은
# 상태를 감지한다.
#
# 사용:
#   scripts/check-plans.sh          # 감지되면 경고 후 exit 1
#   scripts/check-plans.sh --warn    # 경고만 하고 통과 (exit 0)
#
# 한계: 검사 대상이 사용자 홈 디렉토리라 **머신에 종속된다.** CI 에서는 의미가
#       없으므로 로컬 pre-commit 훅에서만 쓴다.
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.."

WARN_ONLY=0
[ "${1:-}" = "--warn" ] && WARN_ONLY=1

# 하니스 계획 디렉토리 탐색 (OS 별 홈 경로 차이를 흡수)
PLAN_DIRS=()
for d in "${HOME:-}/.claude/plans" "${USERPROFILE:-}/.claude/plans"; do
  [ -n "$d" ] && [ -d "$d" ] && PLAN_DIRS+=("$d")
done

if [ "${#PLAN_DIRS[@]}" -eq 0 ]; then
  echo "OK: 하니스 계획 디렉토리가 없음 (이관 대상 없음)"
  exit 0
fi

# $HOME 과 $USERPROFILE 이 같은 곳을 가리킬 수 있어 같은 파일이 두 번 잡힌다.
# 디렉토리를 실제 경로로 정규화해 중복을 없앤다 (find -printf 는 GNU 전용이라 쓰지 않는다).
RESOLVED=()
for d in "${PLAN_DIRS[@]}"; do
  real="$(cd "$d" 2>/dev/null && pwd -P)" || continue
  dup=0
  for seen in "${RESOLVED[@]:-}"; do
    [ "$seen" = "$real" ] && dup=1 && break
  done
  [ "$dup" = "0" ] && RESOLVED+=("$real")
done

found="$(
  for d in "${RESOLVED[@]:-}"; do
    [ -n "$d" ] && find "$d" -maxdepth 1 -type f -name "*.md" 2>/dev/null
  done | sed "s|^|  |"
)"

if [ -z "$found" ]; then
  echo "OK: 이관되지 않은 계획서 없음"
  exit 0
fi

echo "이관되지 않은 계획서가 있습니다:"
echo
printf '%s' "$found"
echo
echo "조치 — docs/plans/README.md 규약:"
echo "  1) docs/plans/YYYY-MM-DD-작업명.md 로 옮긴다 (무작위 이름을 쓰지 않는다)"
echo "  2) 상태 머리글을 붙인다 (실행 커밋 / 결과물 / 계획 이탈 / 계획 오류)"
echo "  3) 원본은 삭제한다 — 두 곳에 남기지 않는다"
echo
echo "진행 중인 계획이라 아직 옮길 수 없다면:"
echo "  scripts/check-plans.sh --warn      # 경고만"
echo "  git commit --no-verify             # 이번 커밋만 훅 건너뛰기"

[ "$WARN_ONLY" = "1" ] && exit 0
exit 1
