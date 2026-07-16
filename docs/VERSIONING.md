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

## 릴리즈 절차

```bash
./scripts/check-version.sh
git commit -m "chore(release): prepare v2.0.0-rc.1"
git tag -a v2.0.0-rc.1 -m "Aerial Survey Manager v2.0.0-rc.1"
git push origin develop
git push origin v2.0.0-rc.1
./scripts/build-release.sh
```

`build-release.sh`는 다음 조건을 만족할 때만 패키지를 만듭니다.

- 모든 버전 표기가 `VERSION`과 일치
- 추적 파일에 커밋되지 않은 변경이 없음
- 동일한 버전의 Git 태그가 현재 `HEAD`를 가리킴
- 개발/배포 Compose 및 배포 경로 검증 통과

완성된 패키지는 다음 형식을 사용합니다.

```text
aerial-survey-manager-v2.0.0-rc.1.tar.gz
```

패키지 안의 `VERSION`과 `BUILD_INFO.txt`에서 버전, Git 커밋, 빌드 시각을
확인할 수 있습니다.
