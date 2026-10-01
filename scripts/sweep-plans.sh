#!/usr/bin/env bash
# =============================================================================
# 계획서 회수 — 하니스 기본 디렉토리에 생성된 계획서를 docs/plans/ 로 옮긴다
#
# 왜 필요한가
# -----------
# `.claude/settings.json` 의 `plansDirectory` 는 **대화형 세션에서 무시된다.**
# 2026-10-01 실측 (Claude Code 2.1.285):
#
#   | 세션 종류                  | 계획서 생성 위치   |
#   | :------------------------- | :----------------- |
#   | 비대화형 (`claude -p`)     | `docs/plans/` ✅   |
#   | 대화형 (평소 쓰는 방식)    | `~/.claude/plans/` |
#
# 대화형 세션 2건의 트랜스크립트 `planFilePath` 가 모두 기본 경로였고,
# `claude -p --permission-mode plan` 프로브는 `docs/plans/` 에 생성했다.
# 폴더는 신뢰 상태(`hasTrustDialogAccepted: true`)였으므로 신뢰 여부와 무관하다.
#
# 훅으로 **생성을 막을 수는 없다** — 파일 생성이 플랜 모드 진입 시점이고 훅
# 이벤트는 그 뒤다 (docs/_private/claude-code-훅-계약-레퍼런스.md §7.3).
# 대신 세션이 끝날 때 **회수**한다. SessionEnd 훅이 이 스크립트를 부른다.
#
# SessionEnd 는 `/clear`·resume·종료에서 모두 발화하므로 평소 흐름을 덮는다.
# 세션이 비정상 종료되면 발화하지 않을 수 있고, 그때는 다음 세션의 SessionEnd
# 나 `check-plans.sh` 검사 3번이 잡는다.
#
# 사용:
#   scripts/sweep-plans.sh            # 회수하고 결과를 출력
#   scripts/sweep-plans.sh --dry-run  # 무엇을 옮길지만 보여준다
#
# 주의: `~/.claude/plans/` 는 **모든 프로젝트가 공유**한다. 다른 프로젝트에서
#       만든 계획서가 섞여 있으면 그것도 이 저장소로 들어온다. 이 훅은 이
#       저장소의 `.claude/settings.json` 에만 등록되어 있으므로 발화 자체는
#       이 프로젝트 세션에서만 일어나지만, 옮기는 대상은 디렉토리 전체다.
#       옮긴 파일은 항상 이름을 출력하므로 섞였다면 눈에 띈다.
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 0

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

DEST="docs/plans"
[ -d "$DEST" ] || exit 0

# -----------------------------------------------------------------------------
# 하니스 기본 디렉토리 — $HOME 과 $USERPROFILE 이 같은 곳을 가리킬 수 있어
# 실제 경로로 정규화해 중복을 없앤다 (check-plans.sh 와 같은 방식).
# -----------------------------------------------------------------------------
RESOLVED=()
n_resolved=0
for d in "${HOME:-}/.claude/plans" "${USERPROFILE:-}/.claude/plans"; do
  [ -n "$d" ] && [ -d "$d" ] || continue
  real="$(cd "$d" 2>/dev/null && pwd -P)" || continue
  dup=0
  if [ "$n_resolved" -gt 0 ]; then
    for seen in "${RESOLVED[@]}"; do
      [ "$seen" = "$real" ] && dup=1 && break
    done
  fi
  if [ "$dup" = "0" ]; then
    RESOLVED+=("$real")
    n_resolved=$((n_resolved + 1))
  fi
done

[ "$n_resolved" -eq 0 ] && exit 0

moved=0
skipped=0

for dir in "${RESOLVED[@]}"; do
  while IFS= read -r src; do
    base="$(basename "$src")"
    dst="$DEST/$base"

    if [ -e "$dst" ]; then
      echo "건너뜀: $base — $DEST 에 같은 이름이 이미 있다 (덮어쓰지 않는다)"
      skipped=$((skipped + 1))
      continue
    fi

    if [ "$DRY_RUN" = "1" ]; then
      echo "옮길 대상: $src -> $dst"
    else
      if mv "$src" "$dst" 2>/dev/null; then
        echo "회수함: $base -> $dst"
      else
        echo "실패: $src 를 옮기지 못했다"
        skipped=$((skipped + 1))
        continue
      fi
    fi
    moved=$((moved + 1))
  done < <(find "$dir" -maxdepth 1 -type f -name "*.md" | sort)
done

if [ "$moved" -gt 0 ] && [ "$DRY_RUN" = "0" ]; then
  cat <<EOF

계획서 ${moved}건을 $DEST 로 회수했다. 아직 규약을 만족하지 않는다:
  1. 이름을 YYYY-MM-DD-작업명.md 로 바꾼다
  2. 상태 머리글을 붙인다 (docs/plans/README.md 참조)
  3. README.md 의 목록 표에 한 줄 추가한다
그때까지 pre-commit 의 check-plans.sh 가 커밋을 막는다.
EOF
fi

# 훅에서 호출되므로 실패로 세션을 어지럽히지 않는다.
exit 0
