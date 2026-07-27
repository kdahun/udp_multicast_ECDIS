# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 빌드 설정 (macOS / Windows 공용, onedir).

빌드: pyinstaller --noconfirm build.spec  (호스트 OS의 실행 파일이 나옴)
  - macOS  -> dist/UDP-Multicast-ECDIS.app
  - Windows-> dist/UDP-Multicast-ECDIS/UDP-Multicast-ECDIS.exe (폴더째 배포)

onedir(폴더) 모드를 쓴다: macOS .app 규격에 맞고 시작이 빠르며 보안 이슈가 없다.
Windows 는 폴더 전체를 zip 으로 묶어 배포하면 된다.

설정 저장 방식:
  기본 설정 mc_config.json / bam_config.json 을 번들에 '읽기전용 리소스'로 포함한다.
  실행 파일은 첫 구동 시 이 기본값을 사용자 데이터 폴더로 복사(seed)하고,
  이후 모든 저장은 그 쓰기 가능한 폴더에 한다 (mcast/core/paths.py 참고).
    macOS  : ~/Library/Application Support/UDP-Multicast-ECDIS
    Windows: %APPDATA%\\UDP-Multicast-ECDIS
"""
import sys

# 번들에 포함할 기본 설정(첫 실행 seed용). sensors_config.json 은 코드에 기본값이
# 있으므로 포함하지 않는다(첫 실행 시 default_config() 로 생성).
datas = [
    ("mc_config.json", "."),
    ("bam_config.json", "."),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir: 바이너리는 COLLECT 로 분리
    name="UDP-Multicast-ECDIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI 앱: 콘솔 창 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,       # macOS: None=현재 아키텍처. universal2 원하면 "universal2"
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="UDP-Multicast-ECDIS",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="UDP-Multicast-ECDIS.app",
        icon=None,
        bundle_identifier="com.example.udp-multicast-ecdis",
        info_plist={"NSHighResolutionCapable": True},
    )
