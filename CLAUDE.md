# BlurFace 작업 규칙

계획: docs/PLAN.md

## Git 규칙
- 브랜치: `main`(릴리스) / `develop`(기본, 통합) / 작업 브랜치 `feature/<내용>`, `fix/<내용>`, `chore/<내용>`, `docs/<내용>`
- 작업 브랜치는 `develop`에서 만들고 PR도 `develop`으로
- 릴리스: `develop -> main` PR, 제목 `release: <요약>`
- 커밋: `<type>: <설명>` (type: feat, fix, chore, ci, docs, refactor, test), 영어 소문자로 시작
- PR 제목: `<type>: <한국어 설명>`
- PR 본문: .github/PULL_REQUEST_TEMPLATE.md (🔵 제목 / ✅ 작업 내용 / 🟠 PR 특이 사항)
- 테스트 영상(mp4)과 모델 파일은 커밋하지 않음
