# BlurFace

완성된 영상의 얼굴을 자동으로 찾아 모자이크한 버전을 만들어 주는 macOS 앱 (Apple Silicon).

## 기능
- 얼굴 자동 검출·추적 (컷 전환, 같은 인물 재등장 대응)
- 인물마다 다른 효과: 모자이크, 블러, 단색, 스티커, 직접 올린 이미지
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
화면에서 고치기: `B`로 상자 편집을 켜고 상자를 끌어 옮기거나 모서리로 크기를 바꿉니다. 빈 곳을 끌면 놓친 얼굴을 새로 그리고,
몇 프레임 건너 한 번 더 그리면 사이는 자동으로 이어집니다. `N`은 확인이 필요한 다음 위치로 이동, `⌘Z`는 실행 취소입니다.

효과: `mosaic[:블록수]` `blur[:강도]` `solid[:#색]` `sticker[:smile|heart]` `image:파일.png` `none`

## 스택
Python 3.12 · PyAV/FFmpeg(VideoToolbox) · ONNX Runtime(CoreML) · SCRFD · ArcFace · PySide6

계획: [docs/PLAN.md](docs/PLAN.md)
