"""설정·데이터 파일 경로 결정 (개발 실행 vs PyInstaller 번들 겸용).

핵심 문제:
  기존 코드는 설정 파일을 소스 파일 기준(Path(__file__).parents[2])에 저장했다.
  PyInstaller 로 묶으면 __file__ 이 번들 내부(onefile=임시 _MEIPASS, .app=번들 내부)를
  가리키는데, 이곳은 읽기전용이거나 종료 시 사라져 설정 저장이 깨진다.

해결:
  - 개발 실행(소스): 지금처럼 저장소 루트에 저장 (기존 동작·추적 파일 유지).
  - 번들 실행(frozen): OS별 사용자 데이터 폴더에 저장 (항상 쓰기 가능).
      macOS  : ~/Library/Application Support/UDP-Multicast-ECDIS
      Windows: %APPDATA%\\UDP-Multicast-ECDIS
      기타    : ~/.local/share/UDP-Multicast-ECDIS
  - 번들 첫 실행 시 사용자 폴더에 설정이 없으면, 번들에 포함된 기본 설정을
    복사해 초기값을 심는다(seed). 기본 설정이 번들에 없으면 그냥 건너뛴다.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "UDP-Multicast-ECDIS"


def is_frozen() -> bool:
    """PyInstaller 등으로 번들된 실행 파일에서 도는가."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """번들에 포함된 읽기전용 리소스(기본 설정 등) 위치."""
    if is_frozen():
        # PyInstaller: onefile=임시 추출 폴더, onedir/.app=실행 폴더. 둘 다 _MEIPASS.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """설정·산출물을 저장할 쓰기 가능한 폴더(없으면 생성)."""
    if not is_frozen():
        base = Path(__file__).resolve().parents[2]        # 저장소 루트(개발)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        root = os.environ.get("APPDATA") or str(Path.home())
        base = Path(root) / APP_NAME
    else:
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(root) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path(name: str) -> Path:
    """설정 파일의 쓰기 경로. 번들 첫 실행 시 기본값이 있으면 복사해 심는다."""
    target = data_dir() / name
    if is_frozen() and not target.exists():
        bundled = resource_dir() / name
        if bundled.exists():
            try:
                shutil.copyfile(bundled, target)
            except OSError:
                pass
    return target
