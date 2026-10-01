#!/usr/bin/env bash
# =============================================================================
# 계획서 규약 검사
#
# 플랜 모드는 계획서를 하니스가 정한 디렉토리에 **무작위 이름**으로 만든다
# (`giggly-knitting-hollerith.md`). 기본값은 `~/.claude/plans/` — 저장소 밖이다.
# 그 자리에 두면 새 세션이 존재를 모르고, 컨텍스트를 비우면 계획의 근거·제외
# 범위를 추적할 수 없다. 실제로 초판 API 설계서 계획이 이렇게 소실됐다.
#
# 이 저장소는 `plansDirectory` 설정으로 생성 위치 자체를 `docs/plans/` 로
# 돌려놓는다. 따라서 **유실은 구조적으로 막히고**, 남는 위험은 이름과 머리글이
# 규약을 벗어나는 것이다. 이 스크립트가 검사하는 것이 바로 그 불변식이다.
#
#   1. `docs/plans/` 안에 YYYY-MM-DD-작업명.md 가 아닌 파일이 있는가
#      (= 플랜 모드가 만든 무작위 이름이 정리되지 않았다)
#   2. 이름은 맞지만 상태 머리글이 없는가
#   3. 하니스 기본 디렉토리에 계획서가 남아 있는가
#      (= 이 클론에 `plansDirectory` 가 설정되지 않았다 — 설정은 `.claude/` 가
#        gitignore 대상이라 커밋되지 않으므로 클론마다 수동이다)
#
# 규약 전문은 docs/plans/README.md 에 있다.
#
# 사용:
#   scripts/check-plans.sh          # 위반이 있으면 안내 후 exit 1
#   scripts/check-plans.sh --warn    # 경고만 하고 통과 (exit 0)
#
# 한계: 검사 3번이 사용자 홈 디렉토리를 본다 — **머신에 종속된다.** CI 에서는
#       의미가 없으므로 로컬 pre-commit 훅에서만 쓴다.
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.."

WARN_ONLY=0
[ "${1:-}" = "--warn" ] && WARN_ONLY=1

PLANS_DIR="docs/plans"
violations=""

add() { violations="${violations}  $1"$'\n'; }

# -----------------------------------------------------------------------------
# 1 · 2. docs/plans/ 안의 이름 규약과 상태 머리글
# -----------------------------------------------------------------------------
if [ -d "$PLANS_DIR" ]; then
  while IFS= read -r f; do
    base="$(basename "$f")"

    # README.md 는 규약 문서 자체다
    [ "$base" = "README.md" ] && continue

    case "$base" in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.md)
        # 이름은 규약을 따른다 — 상태 머리글을 확인한다.
        # 플랜 모드가 쓴 직후에는 머리글이 없다. 머리글은 이관 시 사람이 붙인다.
        if ! head -n 20 "$f" | grep -q "상태:"; then
          add "$f — 상태 머리글이 없다 (**상태: 완료** / **상태: 진행 중**)"
        fi
        ;;
      *.workshop.md)
        add "$f — 플랜 모드 워크샵 파일. 본 계획서로 정리하거나 삭제한다"
        ;;
      *)
        add "$f — 이름이 YYYY-MM-DD-작업명.md 가 아니다 (플랜 모드 무작위 이름)"
        ;;
    esac
  done < <(find "$PLANS_DIR" -maxdepth 1 -type f -name "*.md" | sort)
fi

# -----------------------------------------------------------------------------
# 3. 하니스 기본 디렉토리에 남은 계획서 = plansDirectory 미설정
# -----------------------------------------------------------------------------
# $HOME 과 $USERPROFILE 이 같은 곳을 가리킬 수 있어 같은 파일이 두 번 잡힌다.
# 실제 경로로 정규화해 중복을 없앤다 (find -printf 는 GNU 전용이라 쓰지 않는다).
RESOLVED=()
for d in "${HOME:-}/.claude/plans" "${USERPROFILE:-}/.claude/plans"; do
  [ -n "$d" ] && [ -d "$d" ] || continue
  real="$(cd "$d" 2>/dev/null && pwd -P)" || continue
  dup=0
  for seen in "${RESOLVED[@]:-}"; do
    [ "$seen" = "$real" ] && dup=1 && break
  done
  [ "$dup" = "0" ] && RESOLVED+=("$real")
done

stray=""
for d in "${RESOLVED[@]:-}"; do
  [ -n "$d" ] || continue
  while IFS= read -r f; do
    stray="${stray}  $f"$'\n'
  done < <(find "$d" -maxdepth 1 -type f -name "*.md" 2>/dev/null | sort)
done

# -----------------------------------------------------------------------------
# 보고
# -----------------------------------------------------------------------------
if [ -z "$violations" ] && [ -z "$stray" ]; then
  echo "OK: 계획서 규약 위반 없음"
  exit 0
fi

if [ -n "$violations" ]; then
  echo "$PLANS_DIR 규약 위반:"
  echo
  printf '%s' "$violations"
  echo
  echo "조치 — docs/plans/README.md 규약:"
  echo "  1) YYYY-MM-DD-작업명.md 로 이름을 바꾼다 (무작위 이름을 쓰지 않는다)"
  echo "  2) 상태 머리글을 붙인다 (실행 커밋 / 결과물 / 계획 이탈 / 계획 오류)"
  echo "  3) 본문은 수정하지 않는다 — 어긋난 점은 머리글에 적는다"
  echo
fi

if [ -n "$stray" ]; then
  echo "하니스 기본 디렉토리에 계획서가 남아 있습니다:"
  echo
  printf '%s' "$stray"
  echo
  echo "이 클론에 plansDirectory 가 설정되지 않은 것으로 보입니다."
  echo "  .claude/settings.local.json 에 추가:  \"plansDirectory\": \"docs/plans\""
  echo "  (.claude/ 는 gitignore 대상이라 이 설정은 커밋되지 않는다 — 클론당 1회)"
  echo
  echo "위 파일들은 docs/plans/ 로 옮기고 원본은 삭제한다."
  echo
fi

echo "진행 중인 계획이라 아직 정리할 수 없다면:"
echo "  scripts/check-plans.sh --warn      # 경고만"
echo "  git commit --no-verify             # 이번 커밋만 훅 건너뛰기"

[ "$WARN_ONLY" = "1" ] && exit 0
exit 1
