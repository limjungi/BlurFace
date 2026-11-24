# PyInstaller 설정: uv run pyinstaller packaging/BlurFace.spec  (scripts/build_app.sh 사용)
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = "0.1.0"

# 입력 크기를 고정한 모델 사본만 넣는다 (앱 안에서 새로 만들지 않게)
models = [(str(ROOT / "models/buffalo_l" / f), "models/buffalo_l")
          for f in ("det_10g_640.onnx", "w600k_r50_112.onnx")]

a = Analysis(
    [str(ROOT / "packaging/launcher.py")],
    pathex=[str(ROOT)],
    datas=models,
    hiddenimports=["scipy.optimize", "scipy.sparse.csgraph"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BlurFace", console=False,
          target_arch="arm64", argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="BlurFace")
app = BUNDLE(
    coll,
    name="BlurFace.app",
    icon=str(ROOT / "packaging/BlurFace.icns"),
    bundle_identifier="io.github.limjungi.blurface",
    version=VERSION,
    info_plist={
        "CFBundleName": "BlurFace",
        "CFBundleDisplayName": "BlurFace",
        "CFBundleShortVersionString": VERSION,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.video",
        "NSRequiresAquaSystemAppearance": False,
        # 영상 파일을 앱 아이콘에 끌어다 놓거나 '다음으로 열기'로 열 수 있게
        # .blurface 프로젝트 = 문서 패키지 (Finder에서 파일 하나로 보이고, 더블클릭하면 BlurFace로 열림)
        "UTExportedTypeDeclarations": [{
            "UTTypeIdentifier": "io.github.limjungi.blurface.project",
            "UTTypeDescription": "BlurFace 프로젝트",
            "UTTypeConformsTo": ["com.apple.package", "public.composite-content"],
            "UTTypeIconFile": "BlurFace.icns",
            "UTTypeTagSpecification": {"public.filename-extension": ["blurface"]},
        }],
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "BlurFace 프로젝트",
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "Owner",
            "LSTypeIsPackage": True,
            "CFBundleTypeIconFile": "BlurFace.icns",
            "LSItemContentTypes": ["io.github.limjungi.blurface.project"],
        }, {
            "CFBundleTypeName": "Video",
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "None",  # 영상은 "다음으로 열기"에만. 기본 앱으로 뽑히지 않게
            "LSItemContentTypes": ["public.movie", "public.mpeg-4", "com.apple.quicktime-movie",
                                   "org.matroska.mkv", "org.webmproject.webm"],
        }],
    },
)
