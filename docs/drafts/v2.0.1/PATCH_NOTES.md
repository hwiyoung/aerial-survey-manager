# Aerial Survey Manager v2.0.1 업데이트 안내

> 배포 예정일: 미정
>
> 상태: 작성 중인 초안

## 핵심 업데이트

`v2.0.0`에서 프로젝트 UUID 하위 폴더에 저장되던 최종 정사영상을
다시 `EXPORT_ROOT_PATH` 바로 아래의 사람이 읽기 쉬운 파일명으로 저장합니다.
기존 RC.1 결과는 새 운영 도구로 파일과 DB 경로를 함께 안전하게 변환할 수
있습니다.

## 오류 수정

- 최종 정사영상이 `{project_uuid}` 하위 폴더에 저장되던 회귀를 수정했습니다.
- 다른 프로젝트의 최종 파일명이 같으면 기존 파일을 덮어쓰지 않고
  `{region}_{title} (1).tif`, `(2).tif` 순서로 저장합니다.
- 같은 프로젝트 재처리는 기존 최종 파일명을 유지하면서 완성된 새 COG로
  원자적으로 교체합니다.
- 자동 내보내기와 최종 저장이 같은 결과를 두 번 발행하던 경로를 통합했습니다.

## 운영자 안내

| 항목 | 내용 |
|---|---|
| 컨테이너 재빌드 | 필요: `api`, `worker-engine`, `celery-worker` |
| DB 마이그레이션 | 스키마 변경 없음. RC.1 UUID 폴더 변환 시 파일 경로 레코드를 함께 갱신 |
| 환경변수 | 추가·변경 없음. `AUTO_EXPORT_ENABLED=false` 유지 |
| 데이터 영향 | RC.1 UUID 폴더 결과를 변환할 때만 파일 이동 및 DB 경로 변경 |
| 호환성 | 최종 정사영상 저장 구조를 평면 경로로 복원 |
| 롤백 | 적용 전 DB와 `EXPORT_ROOT_PATH` 전체 백업 필요 |

RC.1에서 생성된 UUID 하위 폴더가 있다면 새 버전 기동 후 먼저 dry-run을
확인합니다.

```bash
./scripts/migrate-orthomosaic-layout.sh
```

출력된 `OLD`/`NEW` 매핑, 자동 번호, 누락·추가 파일 경고를 확인한 뒤에만
적용합니다.

```bash
./scripts/migrate-orthomosaic-layout.sh --apply
```

파일만 수동으로 옮기면 DB가 이전 경로를 계속 가리키므로 수동 `mv`는
사용하지 않습니다. 이 변환 도구는 로컬 스토리지 배포만 지원합니다.

## 알려진 문제

- RC.1 UUID 폴더에 현재 DB가 가리키는 COG 외의 과거 결과가 있으면 자동으로
  옮기지 않습니다.
- MinIO 배포의 UUID 폴더 결과는 이 도구로 변환할 수 없습니다.

## 업데이트 확인

```bash
cat VERSION
curl -fsS http://127.0.0.1:18100/health
```

`VERSION`과 헬스 응답 버전이 모두 `2.0.1`인지 확인합니다.

## 관련 변경

- [PR #7: 정사영상 평면 경로 복구 및 중복 파일명 처리](https://github.com/hwiyoung/aerial-survey-manager/pull/7)
- 세부 변경: `docs/changes/unreleased/fix-orthomosaic-flat-layout.md`
