"""센서 시뮬레이션 문장 도메인 로직 (tkinter 비의존, 순수).

EPFS(DTM/GGA/VTG) · Heading(THS) · SDME(VBW) 문장을 필드 단위로 조립한다.
각 데이터클래스는:
  - body()      : '$'/체크섬을 뺀 문장 본문 (예: 'GPGGA,074455.00,...')
  - warnings()  : 규격상 주의가 필요한 값 조합 안내(막지 않음)
체크섬/헤더 프레이밍은 UI에서 nmea.build_sentence / build_datagram 으로 처리한다.

설정(IP/Port/간격/각 필드값)은 sensors_config.json 에 영속화한다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

SENSORS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "sensors_config.json"


# ---------------------------------------------------------------------------
# 문장 데이터클래스
# ---------------------------------------------------------------------------
@dataclass
class Dtm:
    """DTM — Datum reference (EPFS)."""
    talker: str = "GP"
    datum: str = "W84"       # W84=WGS84 … 999=사용자정의. 모르면 null
    subdiv: str = ""
    lat_off: str = "0.0"     # 분, 항상 양수
    lat_ns: str = "N"
    lon_off: str = "0.0"     # 분, 항상 양수
    lon_ew: str = "E"
    alt_off: str = "0.0"     # m, 음수 가능
    ref_datum: str = "W84"

    def body(self) -> str:
        return (f"{self.talker}DTM,{self.datum},{self.subdiv},"
                f"{self.lat_off},{self.lat_ns},{self.lon_off},{self.lon_ew},"
                f"{self.alt_off},{self.ref_datum}")

    def warnings(self) -> list[str]:
        w: list[str] = []
        if self.datum == "999" and not (self.lat_off.strip() and self.lon_off.strip()):
            w.append("DTM datum=999(사용자 정의): 오프셋(3~7)을 null로 두면 안 됩니다.")
        return w


@dataclass
class Gga:
    """GGA — GPS fix data (EPFS). 폐지예정(→GNS)이나 ECDIS는 수용."""
    talker: str = "GP"
    utc: str = "074455.00"
    lat: str = "3506.2015"
    lat_ns: str = "N"
    lon: str = "12904.6167"
    lon_ew: str = "E"
    quality: str = "1"       # 0만 무효, 1~8 유효. null 금지
    num_sat: str = "11"
    hdop: str = "0.8"
    alt: str = "12.5"        # 안테나 고도(m)
    geoid: str = "21.3"      # Geoidal separation(m)
    dgps_age: str = ""       # DGPS 미사용이면 null
    dgps_id: str = ""

    def body(self) -> str:
        return (f"{self.talker}GGA,{self.utc},{self.lat},{self.lat_ns},"
                f"{self.lon},{self.lon_ew},{self.quality},{self.num_sat},"
                f"{self.hdop},{self.alt},M,{self.geoid},M,"
                f"{self.dgps_age},{self.dgps_id}")

    def warnings(self) -> list[str]:
        w: list[str] = []
        if self.quality.strip() == "":
            w.append("GGA quality indicator(6번)는 null 금지입니다.")
        elif self.quality.strip() == "0":
            w.append("GGA quality=0: 측위 불가/무효 상태로 전송됩니다.")
        return w


@dataclass
class Vtg:
    """VTG — Course over ground and ground speed (EPFS)."""
    talker: str = "GP"
    cog_t: str = "321.4"     # COG 진방위
    cog_m: str = "330.3"     # COG 자방위
    sog_n: str = "12.3"      # SOG 노트 (음수 금지)
    sog_k: str = "22.8"      # SOG km/h (음수 금지)
    mode: str = "A"          # null 금지

    def body(self) -> str:
        return (f"{self.talker}VTG,{self.cog_t},T,{self.cog_m},M,"
                f"{self.sog_n},N,{self.sog_k},K,{self.mode}")

    def warnings(self) -> list[str]:
        w: list[str] = []
        if self.mode.strip() == "":
            w.append("VTG mode indicator(9번)는 null 금지입니다.")
        if self.sog_n.strip().startswith("-") or self.sog_k.strip().startswith("-"):
            w.append("VTG SOG(대지속력)는 음수가 될 수 없습니다(방향은 COG로 표현).")
        return w


@dataclass
class Ths:
    """THS — True heading and status (Heading sensor)."""
    talker: str = "HE"
    heading: str = "321.4"
    mode: str = "A"          # A/E/M/S/V. null 금지. V=무효(standby 포함)

    def body(self) -> str:
        return f"{self.talker}THS,{self.heading},{self.mode}"

    def warnings(self) -> list[str]:
        w: list[str] = []
        if self.mode.strip() == "":
            w.append("THS mode indicator(2번)는 null 금지입니다.")
        elif self.mode.strip().upper() == "V":
            w.append("THS mode=V: 방위 데이터 무효(자이로 기동중/고장)로 전송됩니다.")
        return w


@dataclass
class Vbw:
    """VBW — Dual ground/water speed (SDME). 필드 10개."""
    talker: str = "VD"
    water_long: str = "12.1"          # 1 대수 종방향 (음수=후진)
    water_trans: str = "0.3"          # 2 대수 횡방향 (음수=좌현)
    water_status: str = "A"           # 3 A/V, null 금지
    ground_long: str = "12.3"         # 4 대지 종방향
    ground_trans: str = "0.4"         # 5 대지 횡방향
    ground_status: str = "A"          # 6 A/V, null 금지
    stern_water_trans: str = "-0.2"   # 7 선미 대수 횡방향
    stern_water_status: str = "A"     # 8 A/V, null 금지
    stern_ground_trans: str = "-0.1"  # 9 선미 대지 횡방향
    stern_ground_status: str = "A"    # 10 A/V, null 금지

    def body(self) -> str:
        return (f"{self.talker}VBW,{self.water_long},{self.water_trans},"
                f"{self.water_status},{self.ground_long},{self.ground_trans},"
                f"{self.ground_status},{self.stern_water_trans},"
                f"{self.stern_water_status},{self.stern_ground_trans},"
                f"{self.stern_ground_status}")

    def warnings(self) -> list[str]:
        w: list[str] = []
        pairs = [
            ("water_status", self.water_status), ("ground_status", self.ground_status),
            ("stern_water_status", self.stern_water_status),
            ("stern_ground_status", self.stern_ground_status),
        ]
        empty = [name for name, v in pairs if v.strip() == ""]
        if empty:
            w.append("VBW status 필드는 null 금지(모르면 값은 비우고 status=V): "
                     + ", ".join(empty))
        return w


# 문자열 키 → 데이터클래스 (설정 로드/저장에 사용)
SENTENCE_CLASSES: dict[str, type] = {
    "DTM": Dtm, "GGA": Gga, "VTG": Vtg, "THS": Ths, "VBW": Vbw,
}


def sentence_from_dict(key: str, d: dict) -> object:
    """{필드:값} 딕셔너리로 해당 문장 데이터클래스를 만든다(모르는 키 무시)."""
    cls = SENTENCE_CLASSES[key]
    obj = cls()
    for k, v in (d or {}).items():
        if hasattr(obj, k):
            setattr(obj, k, str(v))
    return obj


def sentence_to_dict(obj) -> dict:
    return asdict(obj)


# ---------------------------------------------------------------------------
# 설정 영속화 (sensors_config.json)
# ---------------------------------------------------------------------------
def _tab_default(ip: str, port: int, sentence_keys: list[str]) -> dict:
    sentences: dict[str, dict] = {}
    for key in sentence_keys:
        d = asdict(SENTENCE_CLASSES[key]())
        d["_enable"] = True
        sentences[key] = d
    return {
        "ip": ip, "port": port, "iface": "", "ttl": 1,
        "interval_ms": 1000, "udpbc": False, "tag": "",
        "sentences": sentences,
    }


def default_config() -> dict:
    return {
        "epfs": _tab_default("239.192.50.82", 5082, ["DTM", "GGA", "VTG"]),
        "heading": _tab_default("239.192.50.80", 5080, ["THS"]),
        "sdme": _tab_default("239.192.50.83", 5083, ["VBW"]),
    }


def load_config(path=SENSORS_CONFIG_PATH) -> dict:
    """설정 로드. 파일이 없거나 깨지면 기본값. 누락 키는 기본값으로 보충."""
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
        for k in ("ip", "port", "iface", "ttl", "interval_ms", "udpbc", "tag"):
            if k in s:
                section[k] = s[k]
        for key, fields in section["sentences"].items():
            fields.update(s.get("sentences", {}).get(key, {}))
    return cfg


def save_config(cfg: dict, path=SENSORS_CONFIG_PATH) -> None:
    Path(path).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
