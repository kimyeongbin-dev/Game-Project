#!/usr/bin/env bash
# =============================================================================
# 컨테이너 베이스 이미지 다이제스트 점검 / 갱신
#
# 이 저장소는 모든 베이스 이미지를 `name:tag@sha256:<digest>` 형식으로 고정한다.
# 태그는 사람이 읽기 위한 것이고, 실제로 받는 것은 다이제스트다
# (태그는 재발행되므로 태그만 쓰면 재현성이 없다).
#
# 대상 파일을 스캔해 각 참조의 태그를 레지스트리에서 다시 해석하고,
# 저장된 다이제스트와 비교한다.
#
# 사용:
#   scripts/update-image-digests.sh            # 점검만 (변경 없음). 차이 있으면 exit 1
#   scripts/update-image-digests.sh --write     # 파일을 최신 다이제스트로 갱신
#
# --write 로 갱신한 뒤에는 반드시 재빌드하고 테스트를 통과시킬 것:
#   docker compose build && docker compose run --rm server-test
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

WRITE=0
[ "${1:-}" = "--write" ] && WRITE=1

TARGETS=(server/Dockerfile client/Dockerfile docker-compose.yml)

# Docker Hub 공식 이미지는 library/ 접두어가 필요하다
docker_hub_repo() {
  case "$1" in
    */*) printf '%s' "$1" ;;
    *)   printf 'library/%s' "$1" ;;
  esac
}

resolve_digest() {
  local image="$1" tag="$2" repo token
  repo="$(docker_hub_repo "$image")"
  token="$(curl -fsS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${repo}:pull" \
           | python -c 'import sys,json; print(json.load(sys.stdin)["token"])')"
  curl -fsS -o /dev/null -D - \
    -H "Authorization: Bearer ${token}" \
    -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json" \
    "https://registry-1.docker.io/v2/${repo}/manifests/${tag}" \
    | tr -d '\r' | awk 'tolower($1)=="docker-content-digest:"{print $2}'
}

status=0
changes=0

for f in "${TARGETS[@]}"; do
  [ -f "$f" ] || continue
  # name:tag@sha256:<64hex> 형태를 모두 수집
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    image="${ref%%:*}"
    rest="${ref#*:}"
    tag="${rest%%@*}"
    old_digest="sha256:${ref##*@sha256:}"

    new_digest="$(resolve_digest "$image" "$tag" || true)"
    if [ -z "$new_digest" ]; then
      echo "  WARN  ${f}: ${image}:${tag} 다이제스트 조회 실패 (네트워크/권한 확인)"
      status=1
      continue
    fi

    if [ "$new_digest" = "$old_digest" ]; then
      echo "  OK    ${f}: ${image}:${tag}"
    else
      changes=$((changes + 1))
      if [ "$WRITE" = "1" ]; then
        python - "$f" "$ref" "${image}:${tag}@${new_digest}" <<'PY'
import sys, pathlib
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
p.write_text(p.read_text(encoding='utf-8').replace(old, new), encoding='utf-8', newline='\n')
PY
        echo "  UPDATE ${f}: ${image}:${tag}"
        echo "         ${old_digest}"
        echo "      -> ${new_digest}"
      else
        echo "  DRIFT ${f}: ${image}:${tag} 다이제스트가 변경되었습니다"
        echo "         저장됨: ${old_digest}"
        echo "         현재  : ${new_digest}"
        status=1
      fi
    fi
  done < <(grep -oE '[a-z0-9._/-]+:[a-zA-Z0-9._-]+@sha256:[0-9a-f]{64}' "$f" | sort -u)
done

echo
if [ "$WRITE" = "1" ]; then
  if [ "$changes" -eq 0 ]; then
    echo "갱신할 항목 없음"
  else
    echo "${changes}건 갱신했습니다. 재빌드 후 테스트를 반드시 통과시키세요:"
    echo "  docker compose build && docker compose run --rm server-test"
  fi
  exit 0
fi

if [ "$status" -ne 0 ]; then
  echo "점검 실패: 업스트림 다이제스트가 저장된 값과 다릅니다."
  echo "의도한 갱신이라면:  scripts/update-image-digests.sh --write"
  echo
  echo "NOTE: 이 스크립트는 CI 의 필수 게이트가 아니다. 업스트림이 보안 패치를"
  echo "      재발행하면 정상적으로 DRIFT 가 뜨며, 그때 의도적으로 갱신한다."
  exit 1
fi
echo "점검 통과: 모든 다이제스트가 업스트림과 일치합니다."
