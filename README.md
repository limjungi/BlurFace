# BlurFace

완성된 영상의 얼굴을 자동으로 찾아 모자이크한 버전을 만들어 주는 macOS 앱 (Apple Silicon).

## 기능
- 얼굴 자동 검출·추적 (컷 전환, 같은 인물 재등장 대응)
- 인물마다 다른 효과: 모자이크, 블러, 단색, 스티커, 직접 올린 이미지
- 추적이 틀린 부분 수동 수정
- 원본 화질·오디오 유지한 채 내보내기 (최대 4K)

## 스택
Python 3.12 · PySide6 · PyAV/FFmpeg · ONNX Runtime(CoreML)

계획: [docs/PLAN.md](docs/PLAN.md)
