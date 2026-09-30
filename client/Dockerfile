# =============================================================================
# 게임모아 클라이언트 툴체인 이미지 (Flutter)
#
# 버전 정책: 로컬 / CI / 컨테이너가 반드시 동일한 Flutter 바이너리를 쓴다.
#   - 단일 기준: 저장소 루트의 `.flutter-version`
#   - 이 Dockerfile 의 FLUTTER_VERSION 기본값은 그 파일을 미러링하며,
#     CI 의 version-guard 잡이 두 값의 불일치를 빌드 실패로 잡는다.
#   - SDK 는 Google 공식 릴리스 아카이브에서 받는다 (로컬 `flutter upgrade` 와 동일 소스).
#     제3자 이미지(ghcr.io/cirruslabs/flutter)는 릴리스를 여러 마이너 버전 뒤늦게 따라오고
#     Dart 버전이 pubspec 의 SDK 제약을 만족하지 못해 사용하지 않는다.
#
# 스테이지 구성
#   flutter-sdk : 공식 아카이브에서 SDK 내려받아 sha256 검증
#   toolchain   : analyze / test / codegen 용 (Android SDK 없음, 슬림)
#   web         : 웹 릴리스 빌드
#   android     : Android AAB/APK 빌드 (compose profile `release` 전용, 수 GB)
#
# root 로 동작한다: 배포되지 않는 빌드 전용 이미지이며,
# 바인드 마운트와 named volume 의 소유권 충돌을 피하기 위한 선택이다.
#
# 주의: 컨테이너는 USB 패스스루/GUI 를 지원하지 않으므로
#       `flutter run` (에뮬레이터/실기기, hot reload) 은 반드시 로컬에서 실행한다.
# =============================================================================
ARG FLUTTER_VERSION=3.47.5
# debian:bookworm-slim — 다이제스트 고정 (태그는 재발행되므로 신뢰하지 않음)
# 갱신은 scripts/update-image-digests.sh 로만 수행한다.
ARG BASE_IMAGE=debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251

# -----------------------------------------------------------------------------
# SDK 취득: 버전만 주면 공식 매니페스트에서 아카이브 경로와 sha256 을 스스로 찾아낸다.
# (버전 외에 동기화해야 할 값이 없도록)
# -----------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS flutter-sdk
ARG FLUTTER_VERSION

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl jq xz-utils \
 && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    manifest="$(curl -fsSL https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json)"; \
    sel="$(printf '%s' "$manifest" | jq -r --arg v "$FLUTTER_VERSION" \
        '[.releases[] | select(.version==$v and .channel=="stable")][0] | "\(.archive)\t\(.sha256)\t\(.dart_sdk_version)"')"; \
    base="$(printf '%s' "$manifest" | jq -r '.base_url')"; \
    archive="$(printf '%s' "$sel" | cut -f1)"; \
    sha="$(printf '%s' "$sel" | cut -f2)"; \
    dart="$(printf '%s' "$sel" | cut -f3)"; \
    if [ "$archive" = "null" ] || [ -z "$archive" ]; then \
        echo "ERROR: Flutter ${FLUTTER_VERSION} (stable/linux) not found in official manifest"; exit 1; \
    fi; \
    echo "Flutter ${FLUTTER_VERSION} / Dart ${dart}"; \
    curl -fsSL -o /tmp/flutter.tar.xz "${base}/${archive}"; \
    echo "${sha}  /tmp/flutter.tar.xz" | sha256sum -c -; \
    mkdir -p /opt; \
    tar -xJf /tmp/flutter.tar.xz -C /opt; \
    rm -f /tmp/flutter.tar.xz

# -----------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS toolchain
ARG FLUTTER_VERSION

ENV FLUTTER_HOME=/opt/flutter \
    PUB_CACHE=/opt/pub-cache \
    CI=true
ENV PATH="${FLUTTER_HOME}/bin:${FLUTTER_HOME}/bin/cache/dart-sdk/bin:${PUB_CACHE}/bin:${PATH}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git unzip xz-utils zip \
 && rm -rf /var/lib/apt/lists/*

COPY --from=flutter-sdk /opt/flutter ${FLUTTER_HOME}

# 엔진 산출물을 이미지에 미리 받아두어 테스트 실행 시 네트워크 의존을 없앤다.
RUN set -eux; \
    git config --global --add safe.directory "${FLUTTER_HOME}"; \
    mkdir -p "${PUB_CACHE}"; \
    flutter config --no-analytics; \
    flutter precache --web; \
    flutter --version

WORKDIR /srv/client

# 의존성 레이어 캐싱: 소스 변경이 pub get 재실행을 유발하지 않도록
COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get

COPY . .
RUN flutter pub get

CMD ["flutter", "test"]

# -----------------------------------------------------------------------------
FROM toolchain AS web
RUN flutter build web --release
# 산출물: /srv/client/build/web

# -----------------------------------------------------------------------------
# Android 빌드 스테이지 — 릴리스 컷 시점에만 사용 (이미지 수 GB)
# 릴리스 서명 키는 이미지에 포함하지 않는다.
# compose 에서 android/key.properties 와 keystore 를 볼륨 마운트로 주입할 것.
# -----------------------------------------------------------------------------
FROM toolchain AS android
ARG ANDROID_CMDLINE_TOOLS_VERSION=13114758

ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${JAVA_HOME}/bin:${PATH}"

# Gradle 8.14 는 Java 17~24 만 지원한다 (로컬 JDK 25 와 달리 여기서는 17 로 고정)
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jdk-headless \
 && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    mkdir -p "${ANDROID_HOME}/cmdline-tools"; \
    curl -fsSL -o /tmp/cmdline-tools.zip \
      "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_CMDLINE_TOOLS_VERSION}_latest.zip"; \
    unzip -q /tmp/cmdline-tools.zip -d "${ANDROID_HOME}/cmdline-tools"; \
    mv "${ANDROID_HOME}/cmdline-tools/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest"; \
    rm -f /tmp/cmdline-tools.zip; \
    yes | sdkmanager --licenses > /dev/null; \
    sdkmanager --install "platform-tools" > /dev/null; \
    flutter config --android-sdk "${ANDROID_HOME}"

CMD ["flutter", "build", "appbundle", "--release"]
