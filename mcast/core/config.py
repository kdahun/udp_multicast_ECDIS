"""설정 영속화 (JSON). tkinter 비의존."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import paths
from .models import MulticastGroup

# 개발 실행: 저장소 루트 / 번들 실행: 사용자 데이터 폴더 (paths 참고)
DEFAULT_CONFIG_PATH = paths.config_path("mc_config.json")


def load_groups(path: os.PathLike | str = DEFAULT_CONFIG_PATH) -> list[MulticastGroup]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [MulticastGroup.from_dict(d) for d in raw]


def save_groups(
    groups: list[MulticastGroup],
    path: os.PathLike | str = DEFAULT_CONFIG_PATH,
) -> None:
    path = Path(path)
    data = [g.to_dict() for g in groups]
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
