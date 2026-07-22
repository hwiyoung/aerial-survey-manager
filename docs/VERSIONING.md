# 버전 정책

이 저장소는 [Semantic Versioning](https://semver.org/) 형식을 사용합니다.
Git 태그와 배포 패키지는 앞에 `v`를 붙이고, 코드 내부 버전은 `v` 없이
기록합니다.

| 변경 종류 | 예시 | 기준 |
|---|---|---|
| 버그 수정 | `v2.0.1` | 기존 API·DB·설정과 호환되는 수정 |
| 기능 추가 | `v2.1.0` | 기존 호환성을 유지하는 기능 추가 |
| 호환성 파괴 | `v3.0.0` | API·DB·환경변수·설치 구조의 호환성이 깨지는 변경 |
| 릴리즈 후보 | `v2.1.0-rc.1` | 운영 검증 전 후보, 수정 시 `rc.2`로 증가 |

## 단일 버전 기준

저장소 루트의 `VERSION` 파일이 기준입니다. 다음 위치는 반드시 같은 버전을
가리켜야 하며 `./scripts/check-version.sh`가 이를 검사합니다.

- `package.json`, `package-lock.json`
- `backend/app/version.py`
- `docs/USER_MANUAL.md`
- `docs/CHANGELOG.md`의 첫 릴리즈 항목

## 개발 PR과 패치노트

일반 기능 개발과 오류 수정 PR에서는 `VERSION`을 변경하지 않습니다. PR마다
버전을 올리면 `package.json`, 사용자 문서, 변경 이력이 반복해서 충돌하고
아직 배포되지 않은 버전이 코드에 노출될 수 있기 때문입니다.

대신 사용자·운영자에게 영향을 주는 PR은
`docs/changes/unreleased/<분류>-<설명>.md` 패치노트 조각을 추가합니다. 조각의
`대상 버전`은 현재 코드 버전이 아니라 변경이 포함될 예정인 릴리즈를
가리킵니다. 작성 형식과 생략 기준은 `docs/changes/README.md`를 따릅니다.

PR 제목은 기존 Conventional Commit 형식을 유지합니다.

```text
feat(upload): 대용량 업로드 재시도 지원
fix(processing): 완료 상태 갱신 오류 수정
perf(map): 대용량 도엽 렌더링 개선
```

## 릴리즈 PR

릴리즈 PR에서만 다음 작업을 함께 수행합니다.

1. 대상 릴리즈에 포함할 패치노트 조각을 확정합니다.
2. 조각을 `docs/changes/<버전>/`으로 이동해 보관합니다.
3. 게임 업데이트 공지 형태의 `docs/PATCH_NOTES_v<버전>.md`를 작성합니다.
4. `docs/CHANGELOG.md` 최상단에 공식 릴리즈 항목을 추가합니다.
5. `VERSION`과 연동된 모든 버전 표기를 동일하게 올립니다.
6. 버전 검사, 테스트, 패키징, 태그, GitHub Release를 순서대로 수행합니다.

`v2.0.0` 이후 정사영상 경로와 덮어쓰기 수정은 `v2.0.1`, 오류 안내·표준 IO·
EO 미리보기·도엽 클립 같은 호환 기능 추가는 `v2.1.0`을 사용합니다. 운영
검증이 필요한 기능 릴리스는 `v2.1.0-rc.1`부터 시작합니다.

현재 운영 검증 후보는 `v2.1.0-rc.3`입니다. 사용자 승인 전에는 정식
`v2.1.0` 태그를 만들지 않습니다.

## 릴리즈 절차

```bash
./scripts/check-version.sh
git commit -m "chore(release): prepare v2.1.0-rc.3"
git tag -a v2.1.0-rc.3 -m "Aerial Survey Manager v2.1.0-rc.3"
git push origin develop
git push origin v2.1.0-rc.3
./scripts/build-release.sh
```

`build-release.sh`는 다음 조건을 만족할 때만 패키지를 만듭니다.

- 모든 버전 표기가 `VERSION`과 일치
- 추적 파일에 커밋되지 않은 변경이 없음
- 동일한 버전의 Git 태그가 현재 `HEAD`를 가리킴
- 개발/배포 Compose 및 배포 경로 검증 통과

완성된 패키지는 다음 형식을 사용합니다.

```text
aerial-survey-manager-v2.1.0-rc.3.tar.gz
```

패키지 안의 `VERSION`과 `BUILD_INFO.txt`에서 버전, Git 커밋, 빌드 시각을
확인할 수 있습니다.
