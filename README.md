# BlurFace

완성된 영상의 얼굴을 자동으로 찾아 모자이크한 버전을 만들어 주는 macOS 앱 (Apple Silicon).

## 기능
- 얼굴 자동 검출·추적 (컷 전환, 같은 인물 재등장 대응)
- 인물마다 다른 효과: 모자이크, 블러, 단색, 스티커, 직접 올린 이미지 (강도·모양·가장자리·범위 조절)
- 같은 인물도 시간 구간마다 다른 효과
- 추적이 틀린 부분 수동 수정: 상자 추가·이동·크기 조절·지우기, 인물 합치기·나누기, 실행 취소
- 원본 화질·오디오 유지한 채 내보내기 (최대 4K, 10bit HDR, 세로 영상)

## 사용법
```sh
uv sync && scripts/download_models.sh

uv run blurface gui                             # 화면으로 열기
uv run blurface run 영상.mp4                    # 영상_mosaic.mp4 생성
uv run blurface persons 영상.mp4                # 인물 번호 확인 (영상.blurface/persons.jpg)
uv run blurface render 영상.mp4 --person 0=sticker:smile --person 3=none
uv run blurface render 영상.mp4 --person-at 0@12-20=sticker:heart   # 인물 0만 12~20초 하트
```
화면 사용법 (파이널컷과 비슷한 배치)
- 아래 타임라인에 인물마다 한 줄. 막대 색이 그 사람에게 걸린 효과 (기본: 타원 블러)
- 줄 왼쪽 효과 버튼을 누르거나 오른쪽 설정에서 효과 변경. 맨 위 "모든 인물" 줄 = 기본 효과
- 인물 줄을 옆으로 끌면 그 시간만 다른 효과. 우클릭으로 이름 바꾸기·합치기(⌘-클릭으로 여럿 선택)·삭제
- `B` 상자 편집: 상자를 끌어 옮기기·모서리로 크기·빈 곳을 끌어 놓친 얼굴 추가. `N` 확인할 곳, `⌘Z` 실행 취소

효과: `mosaic[:블록수]` `blur[:강도]` `solid[:#색]` `sticker[:smile|heart]` `image:파일.png` `none`
옵션(쉼표로 이어 붙임): `shape=rect|rounded|ellipse` 모양, `feather=0~50` 가장자리 부드럽게, `scale=50~300` 가리는 범위(%)
예: `--person 2=blur:40,shape=ellipse,feather=20`

## 스택
Python 3.12 · PyAV/FFmpeg(VideoToolbox) · ONNX Runtime(CoreML) · SCRFD · ArcFace · PySide6

계획: [docs/PLAN.md](docs/PLAN.md)
