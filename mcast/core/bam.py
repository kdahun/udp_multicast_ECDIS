"""BAM(Bridge Alert Management) 도메인 로직 (tkinter 비의존).

- ALF / ALC 문장 파싱
- AlertStore : 알람 상태 저장소 (ALF·ALC를 같은 키로 통합)
- ACN datagram 빌더 (ACK/Silence 명령)
- BamSettings : 소스/대상 ID, ACN 대상 그룹 등 (JSON 영속화)

알람 식별키 = (mnemonic, alert_id, instance)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import time as _now

from . import nmea, paths

BAM_CONFIG_PATH = paths.config_path("bam_config.json")

# ACN 명령
CMD_ACK = "A"        # Acknowledge
CMD_SILENCE = "S"    # Temporary silence
CMD_REQUEST = "Q"    # Request/repeat
CMD_TRANSFER = "O"   # Responsibility transfer

# Alert state(7번 필드) 사람이 읽는 이름
STATE_NAMES = {
    "V": "active-unack", "S": "silenced", "A": "acknowledged",
    "O": "resp-transferred", "U": "rectified-unack", "N": "normal",
}


# ---------------------------------------------------------------------------
# 문장 모델
# ---------------------------------------------------------------------------
@dataclass
class AlfSentence:
    total: int
    num: int
    seq_id: str
    time: str
    category: str
    priority: str
    state: str
    mnemonic: str
    alert_id: str
    instance: str
    revision: str
    escalation: str
    text: str


@dataclass
class AlcEntry:
    mnemonic: str
    alert_id: str
    instance: str
    revision: str


@dataclass
class AlcSentence:
    total: int
    num: int
    seq_id: str
    count: int
    entries: list[AlcEntry]


def _get(fields: list[str], i: int) -> str:
    return fields[i] if i < len(fields) else ""


def parse_alf(fields: list[str]) -> AlfSentence:
    """fields: ['EIALF','2','1','0','105414.14','B','W','V','MRL','9025','81','40','3','GYRO SIG Change']"""
    return AlfSentence(
        total=int(_get(fields, 1) or 0),
        num=int(_get(fields, 2) or 0),
        seq_id=_get(fields, 3),
        time=_get(fields, 4),
        category=_get(fields, 5),
        priority=_get(fields, 6),
        state=_get(fields, 7),
        mnemonic=_get(fields, 8),
        alert_id=_get(fields, 9),
        instance=_get(fields, 10),
        revision=_get(fields, 11),
        escalation=_get(fields, 12),
        text=_get(fields, 13),
    )


def parse_alc(fields: list[str]) -> AlcSentence:
    """fields: ['EIALC','01','01','00','3', m,id,inst,rev, m,id,inst,rev, ...]"""
    entries: list[AlcEntry] = []
    rest = fields[5:]
    for k in range(0, len(rest) - 3, 4):
        m, i, ins, rev = rest[k:k + 4]
        if m == "" and i == "" and ins == "" and rev == "":
            continue                       # 빈 엔트리(엔트리 수 0 호환)
        entries.append(AlcEntry(m, i, ins, rev))
    return AlcSentence(
        total=int(_get(fields, 1) or 0),
        num=int(_get(fields, 2) or 0),
        seq_id=_get(fields, 3),
        count=int(_get(fields, 4) or 0),
        entries=entries,
    )


# ---------------------------------------------------------------------------
# 알람 저장소
# ---------------------------------------------------------------------------
@dataclass
class Alert:
    mnemonic: str
    alert_id: str
    instance: str
    category: str = ""
    priority: str = ""
    state: str = ""
    revision: str = ""
    escalation: str = ""
    title: str = ""
    description: str = ""
    time: str = ""
    in_alc: bool = False
    last_seen: float = field(default_factory=_now)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.mnemonic, self.alert_id, self.instance)


class AlertStore:
    """ALF·ALC를 (mnemonic, id, instance) 키로 통합 관리."""

    def __init__(self) -> None:
        self.alerts: dict[tuple[str, str, str], Alert] = {}
        self.alc_entries: list[AlcEntry] = []
        self._alc_buf: dict[str, dict[int, list[AlcEntry]]] = {}

    # --- 입력 ------------------------------------------------------------
    def feed_datagram(self, dg: "nmea.Datagram") -> str | None:
        """파싱된 datagram을 반영. 반영한 종류('ALF'/'ALC') 또는 None."""
        if dg.formatter == "ALF":
            self._feed_alf(parse_alf(dg.fields))
            return "ALF"
        if dg.formatter == "ALC":
            self._feed_alc(parse_alc(dg.fields))
            return "ALC"
        return None

    def _feed_alf(self, alf: AlfSentence) -> None:
        key = (alf.mnemonic, alf.alert_id, alf.instance)
        a = self.alerts.get(key)
        if a is None:
            a = Alert(alf.mnemonic, alf.alert_id, alf.instance)
            self.alerts[key] = a
        if alf.num <= 1:                    # 제목 문장(또는 단일 문장): 메타 포함
            a.time = alf.time
            a.category = alf.category
            a.priority = alf.priority
            a.state = alf.state
            a.title = alf.text
        if alf.num == 2:                    # 설명 문장
            a.description = alf.text
        if alf.revision:
            a.revision = alf.revision
        if alf.escalation:
            a.escalation = alf.escalation
        a.last_seen = _now()
        a.in_alc = key in self._alc_keys()

    def _feed_alc(self, alc: AlcSentence) -> None:
        buf = self._alc_buf.setdefault(alc.seq_id, {})
        buf[alc.num] = alc.entries
        if alc.total and len(buf) >= alc.total:
            entries: list[AlcEntry] = []
            for n in sorted(buf):
                entries.extend(buf[n])
            self.alc_entries = entries
            del self._alc_buf[alc.seq_id]
            self._mark_alc()

    def _alc_keys(self) -> set[tuple[str, str, str]]:
        return {(e.mnemonic, e.alert_id, e.instance) for e in self.alc_entries}

    def _mark_alc(self) -> None:
        keys = self._alc_keys()
        for key, a in self.alerts.items():
            a.in_alc = key in keys

    # --- 조회 ------------------------------------------------------------
    def get(self, key: tuple[str, str, str]) -> Alert | None:
        return self.alerts.get(key)

    def list_alerts(self) -> list[Alert]:
        return list(self.alerts.values())


# ---------------------------------------------------------------------------
# ACN 빌더 + 검증
# ---------------------------------------------------------------------------
def acn_warnings(category: str, instance: str, command: str) -> list[str]:
    """규격상 문제 소지가 있는 조합을 경고 문자열로 반환(막지는 않음)."""
    warns: list[str] = []
    if command == CMD_ACK and category == "A":
        warns.append("Category A 알람: 원격 ACK(A)는 규격상 거부될 수 있습니다.")
    if command in (CMD_ACK, CMD_TRANSFER) and str(instance) == "0":
        warns.append(f"인스턴스 0 + 명령 {command}: 규격상 불가(모든 인스턴스 의미).")
    return warns


def build_acn(mnemonic: str, alert_id: str, instance: str, alert_time: str,
              command: str, settings: "BamSettings", seq_n: int) -> bytes:
    """ACN datagram(raw 바이트)을 만든다. 필드는 대상 알람을 그대로 미러링."""
    talker = (settings.source_id[:2] or "CA").upper()
    body = (f"{talker}ACN,{alert_time},{mnemonic},{alert_id},"
            f"{instance},{command},C")
    tag_body = f"s:{settings.source_id},d:{settings.dest_id},n:{seq_n}"
    if settings.tag_extra:
        tag_body += "," + settings.tag_extra
    return nmea.build_datagram(tag_body, body)


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
@dataclass
class BamSettings:
    source_id: str = "CA0001"       # 우리 콘솔 (s:) → talker는 앞 2자
    dest_id: str = "EI0001"         # 대상 (d:)
    acn_ip: str = "239.192.0.19"    # ACN 송신 멀티캐스트 그룹
    acn_port: int = 60019
    acn_iface: str = ""
    acn_ttl: int = 1
    tag_extra: str = "x:Nav,z:Nav"  # 수신 장비가 쓰던 커스텀 태그 미러링

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "BamSettings":
        base = cls()
        for k, v in d.items():
            if hasattr(base, k):
                setattr(base, k, v)
        base.acn_port = int(base.acn_port)
        base.acn_ttl = int(base.acn_ttl)
        return base


def load_bam_settings(path=BAM_CONFIG_PATH) -> BamSettings:
    path = Path(path)
    if not path.exists():
        return BamSettings()
    try:
        return BamSettings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return BamSettings()


def save_bam_settings(settings: BamSettings, path=BAM_CONFIG_PATH) -> None:
    Path(path).write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
