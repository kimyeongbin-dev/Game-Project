-- 테스트 전용 데이터베이스.
-- conftest.py 가 매 테스트마다 create_all/drop_all 을 수행하므로
-- 개발용 DB와 반드시 분리해야 한다.
--
-- NOTE: docker-entrypoint-initdb.d 는 데이터 볼륨이 비어 있을 때만 실행된다.
--       기존 볼륨을 쓰던 중이라면 `docker compose down -v` 로 초기화가 필요하다.
CREATE DATABASE gamemoa_test;
