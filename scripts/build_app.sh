#!/bin/sh
# BlurFace.app과 BlurFace.dmg 만들기 → dist/
set -e
cd "$(dirname "$0")/.."
[ -f models/buffalo_l/det_10g.onnx ] || scripts/download_models.sh
# 입력 크기 고정 모델 사본을 미리 만들어 둠 (앱 안에서는 만들지 않음)
uv run python -c "from blurface.detect.scrfd import fixed_size_model as f; f('models/buffalo_l/det_10g.onnx', 640); f('models/buffalo_l/w600k_r50.onnx', 112)"
rm -rf build dist
uv run pyinstaller --noconfirm --log-level WARN packaging/BlurFace.spec
# dmg: 앱 + 응용 프로그램 폴더 바로가기
VERSION=$(grep '^VERSION' packaging/BlurFace.spec | cut -d'"' -f2)
STAGE=build/dmg
mkdir -p "$STAGE"
cp -R dist/BlurFace.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "BlurFace" -srcfolder "$STAGE" -format UDZO -ov "dist/BlurFace-$VERSION.dmg"
du -sh dist/BlurFace.app "dist/BlurFace-$VERSION.dmg"
