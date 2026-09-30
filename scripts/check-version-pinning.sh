#!/usr/bin/env bash
# =============================================================================
# 버전 고정 규율 검사
#
# 이 프로젝트는 "자동으로 변경되거나 업그레이드되는 일이 절대 없어야 한다"는
# 원칙을 따른다. 이 스크립트는 그 규율이 깨진 지점을 찾는다.
#
# 검사 항목
#   1) server/pyproject.toml   : 직접 의존성이 모두 `==` 인가
#   2) server/uv.lock          : 존재하는가 (전이 의존성 고정)
#   3) 컨테이너 이미지         : 모두 @sha256: 다이제스트가 붙어 있는가
#   4) client/pubspec.yaml     : 캐럿/범위 제약이 없는가
#   5) client/pubspec.lock     : 존재하는가
#   6) GitHub Actions          : 모두 40자 커밋 SHA 로 고정되어 있는가
#   7) Android SDK             : flutter.* 위임 없이 명시 고정되어 있는가
#
# 다이제스트가 업스트림과 일치하는지(최신인지)는 검사하지 않는다.
# 그것은 scripts/update-image-digests.sh 의 역할이다.
#
# 사용: scripts/check-version-pinning.sh
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.."

status=0
fail() { echo "  FAIL $*"; status=1; }
ok() { echo "  OK   $*"; }

# ---------------------------------------------------------------------------
# Python 인터프리터 탐지
#
# Windows 에서 `python3` 는 Microsoft Store 스텁일 수 있다. 이 스텁은 stderr 로
# 안내만 출력하고 종료하므로, 검사 결과가 빈 문자열이 되어 위반을 조용히
# 통과시킨다. 실제로 코드를 실행할 수 있는 인터프리터를 찾아야 한다.
# ---------------------------------------------------------------------------
PY_BIN=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
    PY_BIN="$candidate"
    break
  fi
done
if [ -z "$PY_BIN" ]; then
  echo "FAIL: Python 3.11+ 인터프리터를 찾을 수 없습니다 (tomllib 필요)"
  echo "      검사를 건너뛰지 않고 실패로 처리합니다 — 조용한 통과를 막기 위함입니다."
  exit 1
fi

echo "[1] server/pyproject.toml — 직접 의존성 == 고정"
# grep ERE 브래킷 표현식은 백슬래시 이스케이프를 지원하지 않아
# "[A-Za-z0-9_.\[\]-]+" 같은 패턴이 조용히 깨진다. TOML 을 실제로 파싱한다.
loose="$("$PY_BIN" scripts/_check_pyproject_pins.py)"
if [ -n "$loose" ]; then
  fail "== 고정이 아닌 의존성 발견:"
  printf '%s\n' "$loose" | sed 's/^/        /'
else
  ok "모두 == 고정"
fi

echo "[2] server/uv.lock — 전이 의존성 고정"
if [ -f server/uv.lock ]; then
  n="$(grep -c '^\[\[package\]\]' server/uv.lock || echo 0)"
  ok "존재 (${n} 패키지)"
else
  fail "uv.lock 없음 — 전이 의존성이 매 빌드 재해석됩니다"
fi

echo "[3] 컨테이너 이미지 — @sha256 다이제스트"
for f in server/Dockerfile client/Dockerfile docker-compose.yml; do
  [ -f "$f" ] || continue
  refs="$(grep -hoE '(^FROM +[^ ]+|^ARG +[A-Z_]*IMAGE=[^ ]+|image: *[^ ]+)' "$f" |
    sed -E 's/^FROM +//; s/^ARG +[A-Z_]*IMAGE=//; s/^image: *//' |
    grep -vE '^\$\{' || true)"
  while IFS= read -r r; do
    [ -n "$r" ] || continue
    # 내부 스테이지 이름은 이미지 참조가 아니다
    case "$r" in
    base | deps | deps-dev | dev | test | prod | toolchain | web | android | flutter-sdk) continue ;;
    esac
    if printf '%s' "$r" | grep -qE '@sha256:[0-9a-f]{64}$'; then
      ok "$f: $r"
    else
      fail "$f: '$r' 에 다이제스트가 없습니다 (태그는 재발행됩니다)"
    fi
  done <<<"$refs"
done

echo "[4] client/pubspec.yaml — 범위 제약 금지"
loose="$(grep -nE '^\s+[a-z0-9_]+: *[\^>~<]' client/pubspec.yaml || true)"
if [ -n "$loose" ]; then
  fail "범위 제약 발견:"
  printf '%s\n' "$loose" | sed 's/^/        /'
else
  ok "모두 정확 버전"
fi
sdk="$(sed -n 's/^  sdk: *//p' client/pubspec.yaml | head -1)"
case "$sdk" in
[0-9]*.[0-9]*.[0-9]*) ok "Dart SDK 제약 정확 고정 ($sdk)" ;;
*) fail "Dart SDK 제약이 정확 고정이 아닙니다 ('$sdk')" ;;
esac

echo "[4b] client/analysis_options.yaml — 플러그인 버전 고정"
plug="$(grep -nE '^\s+[a-z0-9_]+: *[\^>~<]' client/analysis_options.yaml || true)"
if [ -n "$plug" ]; then
  fail "플러그인 범위 제약 발견:"
  printf '%s\n' "$plug" | sed 's/^/        /'
else
  ok "정확 버전"
fi

echo "[5] client/pubspec.lock"
if [ -f client/pubspec.lock ]; then ok "존재"; else fail "pubspec.lock 없음"; fi

echo "[6] GitHub Actions — 커밋 SHA 고정"
bad="$(grep -rnE 'uses: *[^ ]+@(v[0-9]|main|master)' .github/workflows/ || true)"
if [ -n "$bad" ]; then
  fail "이동 가능한 ref 발견:"
  printf '%s\n' "$bad" | sed 's/^/        /'
else
  cnt="$(grep -rhoE 'uses: *[^ ]+@[0-9a-f]{40}' .github/workflows/ | wc -l | tr -d ' ')"
  ok "모두 40자 SHA 고정 (${cnt}건)"
fi

echo "[7] Android SDK — flutter.* 위임 금지 (versionCode/Name 제외)"
deleg="$(grep -nE '(compileSdk|minSdk|targetSdk|ndkVersion) *= *flutter\.' client/android/app/build.gradle.kts || true)"
if [ -n "$deleg" ]; then
  fail "flutter.* 위임 발견 (Flutter 버전 변경 시 조용히 바뀝니다):"
  printf '%s\n' "$deleg" | sed 's/^/        /'
else
  ok "compileSdk / minSdk / targetSdk / ndkVersion 명시 고정"
fi

echo
if [ "$status" -ne 0 ]; then
  echo "버전 고정 규율 위반이 있습니다."
  exit 1
fi
echo "버전 고정 규율 통과. (python=$PY_BIN)"
