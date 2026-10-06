"""타깃(선박) 시뮬레이션 문장 도메인 로직 (tkinter 비의존, 순수).

- Radar : TTM (Tracked target message)  — talker 기본 RA, '$' 문장
- AIS   : VDM (VHF data-link message)    — talker 기본 AI, '!' 문장
          ITU-R M.1371 Type 1 페이로드를 168비트 패킹 + 6비트 아머링으로 생성.

각 데이터클래스는 sentence() 로 완성된 NMEA 문장(체크섬 포함)을 돌려준다.
탭에서 UdPbC 프레이밍/CRLF 를 씌운다.

여러 선박을 다루므로 설정은 '선박 리스트' 구조로 targets_config.json 에 저장한다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import nmea, paths

TARGETS_CONFIG_PATH = paths.config_path("targets_config.json")


# ---------------------------------------------------------------------------
# 6비트 아머링 / 비트 패킹
# ---------------------------------------------------------------------------
def _bits(value: int, width: int) -> str:
    """정수를 width 비트 이진 문자열로. 음수는 2의 보수(width 비트)."""
    return format(value & ((1 << width) - 1), f"0{width}b")


def armor(bitstr: str) -> tuple[str, int]:
    """비트 문자열 → (6비트 아머 페이로드, fill-bits 개수)."""
    fill = (6 - len(bitstr) % 6) % 6
    bitstr += "0" * fill
    out = []
    for i in range(0, len(bitstr), 6):
        v = int(bitstr[i:i + 6], 2)
        out.append(chr(v + 48) if v < 40 else chr(v + 56))
    return "".join(out), fill


def build_ais_type1(mmsi: int, nav_status: int, rot: int, sog: int,
                    pos_accuracy: int, lon: int, lat: int, cog: int,
                    heading: int, timestamp: int, maneuver: int, raim: int,
                    repeat: int = 0, radio: int = 0) -> tuple[str, int]:
    """Type 1 Position report 168비트를 만들어 (페이로드, fill-bits) 반환.

    lon/lat 는 '도 × 600000'(1/10000분) 정수, sog 는 ×10, cog 는 ×10 단위.
    """
    b = "".join([
        _bits(1, 6),               # Message ID = 1
        _bits(repeat, 2),          # Repeat indicator
        _bits(mmsi, 30),           # MMSI
        _bits(nav_status, 4),      # Navigational status
        _bits(rot, 8),             # ROT (raw)
        _bits(sog, 10),            # SOG ×10
        _bits(pos_accuracy, 1),    # Position accuracy
        _bits(lon, 28),            # Longitude (signed)
        _bits(lat, 27),            # Latitude (signed)
        _bits(cog, 12),            # COG ×10
        _bits(heading, 9),         # True heading
        _bits(timestamp, 6),       # Time stamp
        _bits(maneuver, 2),        # Manoeuvre indicator
        _bits(0, 3),               # Spare
        _bits(raim, 1),            # RAIM flag
        _bits(radio, 19),          # Radio status
    ])
    return armor(b)                # 168 = 6×28 → fill-bits 항상 0


# ---------------------------------------------------------------------------
# TTM (Radar)
# ---------------------------------------------------------------------------
@dataclass
class Ttm:
    talker: str = "RA"
    target_num: str = "01"       # 0~999
    distance: str = "5.27"       # 단위는 units
    bearing: str = "358.7"       # 도
    bearing_tr: str = "T"        # T=진, R=상대
    speed: str = "1.3"
    course: str = "359.0"
    course_tr: str = "T"
    cpa: str = "3.19"
    tcpa: str = "-193.89"        # - = 멀어짐
    units: str = "N"             # K/N/S
    name: str = "TEST_SHIP"
    status: str = "T"            # L=Lost, Q=획득중, T=추적중
    ref_target: str = ""         # R 또는 null
    utc: str = "003717.92"
    acq_type: str = "A"          # A/M/R

    def body(self) -> str:
        return (f"{self.talker}TTM,{self.target_num},{self.distance},"
                f"{self.bearing},{self.bearing_tr},{self.speed},{self.course},"
                f"{self.course_tr},{self.cpa},{self.tcpa},{self.units},"
                f"{self.name},{self.status},{self.ref_target},{self.utc},"
                f"{self.acq_type}")

    def sentence(self) -> str:
        return nmea.build_sentence(self.body())     # '$'+body+'*cs'

    def warnings(self) -> list[str]:
        w: list[str] = []
        if self.status.strip().upper() not in ("L", "Q", "T", ""):
            w.append(f"TTM status(12번) 값이 이상합니다: {self.status} (L/Q/T)")
        if self.units.strip().upper() not in ("K", "N", "S", ""):
            w.append(f"TTM units(10번) 값이 이상합니다: {self.units} (K/N/S)")
        return w


# ---------------------------------------------------------------------------
# VDM (AIS)
# ---------------------------------------------------------------------------
@dataclass
class Vdm:
    talker: str = "AI"
    channel: str = "A"           # A/B, 없으면 null
    mmsi: str = "607125003"
    nav_status: str = "8"        # 0~15
    rot: str = "128"             # raw (128=미제공)
    sog: str = "10.0"            # 노트
    pos_accuracy: str = "0"
    lon: str = "129.187318"      # 도
    lat: str = "35.099088"       # 도
    cog: str = "81.0"            # 도
    heading: str = "81"          # 도 (511=미제공)
    timestamp: str = "16"        # 초
    maneuver: str = "1"
    raim: str = "0"

    def payload_and_fill(self) -> tuple[str, int]:
        f = lambda s: float(s) if str(s).strip() != "" else 0.0
        i = lambda s: int(float(s)) if str(s).strip() != "" else 0
        return build_ais_type1(
            mmsi=i(self.mmsi),
            nav_status=i(self.nav_status),
            rot=i(self.rot),
            sog=round(f(self.sog) * 10),
            pos_accuracy=i(self.pos_accuracy),
            lon=round(f(self.lon) * 600000),
            lat=round(f(self.lat) * 600000),
            cog=round(f(self.cog) * 10),
            heading=i(self.heading),
            timestamp=i(self.timestamp),
            maneuver=i(self.maneuver),
            raim=i(self.raim),
        )

    def body(self) -> str:
        payload, fill = self.payload_and_fill()
        # 단일 문장: total=1, num=1, seq=null
        return f"{self.talker}VDM,1,1,,{self.channel},{payload},{fill}"

    def sentence(self) -> str:
        b = self.body()
        return f"!{b}*{nmea.checksum_hex(b)}"        # '!'+body+'*cs'

    def warnings(self) -> list[str]:
        w: list[str] = []
        digits = self.mmsi.strip()
        if digits and (not digits.isdigit() or len(digits) != 9):
            w.append(f"MMSI 는 보통 9자리 숫자입니다: {self.mmsi}")
        try:
            if not (0 <= int(self.nav_status) <= 15):
                w.append("nav status 는 0~15 범위입니다.")
        except ValueError:
            w.append("nav status 가 숫자가 아닙니다.")
        return w


# ---------------------------------------------------------------------------
# 선박 데이터클래스 매핑 / 직렬화
# ---------------------------------------------------------------------------
SHIP_CLASSES: dict[str, type] = {"radar": Ttm, "ais": Vdm}


def ship_from_dict(kind: str, d: dict):
    cls = SHIP_CLASSES[kind]
    obj = cls()
    for k, v in (d or {}).items():
        if k != "_enable" and hasattr(obj, k):
            setattr(obj, k, str(v))
    return obj


# ---------------------------------------------------------------------------
# 설정 영속화 (targets_config.json) — 선박 리스트 구조
# ---------------------------------------------------------------------------
def _tab_default(ip: str, port: int, kind: str, n: int = 1) -> dict:
    cls = SHIP_CLASSES[kind]
    ships = []
    for _ in range(n):
        d = asdict(cls())
        d["_enable"] = True
        ships.append(d)
    return {
        "ip": ip, "port": port, "iface": "", "ttl": 1,
        "interval_sec": 3, "udpbc": False, "tag": "",
        "ships": ships,
    }


def default_config() -> dict:
    return {
        "radar": _tab_default("239.192.0.9", 5079, "radar"),
        "ais": _tab_default("239.192.50.82", 5082, "ais"),
    }


def load_config(path=TARGETS_CONFIG_PATH) -> dict:
    cfg = default_config()
    path = Path(path)
    if not path.exists():
        return cfg
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return cfg
    for tab, section in cfg.items():
        s = saved.get(tab, {})
        for k in ("ip", "port", "iface", "ttl", "interval_sec", "udpbc", "tag"):
            if k in s:
                section[k] = s[k]
        if isinstance(s.get("ships"), list):
            section["ships"] = s["ships"]      # 빈 리스트도 그대로(선박 0척 허용)
    return cfg


def save_config(cfg: dict, path=TARGETS_CONFIG_PATH) -> None:
    Path(path).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
