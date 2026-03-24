# 개발 로드맵

## 현재 상태

| Phase | 상태 |
|-------|------|
| Phase 1~4: Foundation~Dashboard | ✅ 완료 |
| Phase 5: TiTiler, 통계, 내보내기 | ✅ 완료 |
| Phase 6: TB급 업로드, 라이선스 | ✅ 완료 |
| Phase 7: 멀티 업로드, UI 개선 | ✅ 완료 |
| Phase 8: 로컬/MinIO 스토리지 추상화 | ✅ 완료 |

## 향후 계획

- [ ] ODM/External 엔진 재활성화
- [ ] N+1 쿼리 개선 (프로젝트 목록 joinedload)
- [ ] 사이드바 폴링 → WebSocket 전환
- [ ] 다운로드 토큰 스코프 정책 통일
- [ ] 그룹 삭제 정합성 점검

## Known Issues

| 구분 | 내용 |
|------|------|
| 성능 | 프로젝트 목록 N+1 쿼리 — 페이지당 60+ DB 쿼리 발생 |
| 성능 | 사이드바 5초 폴링 — WebSocket 이벤트로 대체 가능 |
| 코드 | download.py bare except — 실패 시 로깅 없이 무시 |
| 코드 | upload.py print()/logger 혼용 |
| 안전성 | 처리 태스크 멱등성 — DB 트랜잭션 원자성 부족 |
| 인프라 | 컨테이너 리소스 제한 없음 (mem_limit, cpus) |
| 인프라 | DB 커넥션 풀 기본값 (pool_size=5) |
| 지도 | 처리 중단 후 재시작 시 Empty DEM 오류 가능 (EO 재업로드 권장) |
| 지도 | 오프라인 타일 사용 시 `VITE_MAP_OFFLINE=true` 필요 |
| 저장소 | MinIO 디스크 여유 10% 미만 시 HTTP 507 오류 |

*마지막 업데이트: 2026-03-24*
