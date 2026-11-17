#!/bin/sh
# 얼굴 모델 받기 (YuNet, SCRFD-10G, ArcFace)
set -e
cd "$(dirname "$0")/../models" 2>/dev/null || { mkdir -p "$(dirname "$0")/../models"; cd "$(dirname "$0")/../models"; }
curl -sSL -o yunet.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
curl -sSL -o buffalo_l.zip https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -o -q buffalo_l.zip det_10g.onnx w600k_r50.onnx -d buffalo_l && rm buffalo_l.zip
echo "done"
