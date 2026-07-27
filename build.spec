# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 빌드 설정 (OS별 분기).

빌드: pyinstaller --noconfirm build.spec  (호스트 OS의 실행 파일이 나옴)
  - Windows -> dist/UDP-Multicast-ECDIS.exe   (단일 파일 onefile. 이 exe 하나만 복사하면 됨)
  - macOS   -> dist/UDP-Multicast-ECDIS.app    (.app 규격상 폴더 번들 onedir)

왜 OS별로 다른가:
  Windows 는 onefile(단일 exe)이 배포가 편하다 — 파일 하나만 옮기면 실행된다.
  macOS 는 .app 이 onefile 과 맞지 않아(보안·규격) onedir 번들을 쓴다.

설정 저장 방식:
  기본 설정 mc_config.json / bam_config.json 을 번들에 '읽기전용 리소스'로 포함한다.
  실행 파일은 첫 구동 시 이 기본값을 사용자 데이터 폴더로 복사(seed)하고,
  이후 모든 저장은 그 쓰기 가능한 폴더에 한다 (mcast/core/paths.py 참고).
    Windows: %APPDATA%\\UDP-Multicast-ECDIS
    macOS  : ~/Library/Application Support/UDP-Multicast-ECDIS
  onefile exe 는 매 실행 시 임시폴더로 풀리지만, 설정은 %APPDATA% 에 저장되므로
  exe 를 옮기거나 재실행해도 설정이 유지된다.
"""
import sys

IS_MAC = sys.platform == "darwin"

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

# 공통 EXE 옵션
_exe_kwargs = dict(
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

if IS_MAC:
    # macOS: onedir + .app 번들
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_exe_kwargs)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   upx_exclude=[], name="UDP-Multicast-ECDIS")
    app = BUNDLE(
        coll,
        name="UDP-Multicast-ECDIS.app",
        icon=None,
        bundle_identifier="com.example.udp-multicast-ecdis",
        info_plist={"NSHighResolutionCapable": True},
    )
else:
    # Windows/Linux: onefile (단일 실행 파일). exe 하나만 복사하면 됨.
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **_exe_kwargs)
