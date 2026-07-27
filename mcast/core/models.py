"""도메인 모델 (tkinter 비의존, 순수 데이터).

- MulticastGroup : 하나의 멀티캐스트 그룹 설정
- ReceivedMessage: 수신한 메시지 1건
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MulticastGroup:
    """UDP 멀티캐스트 그룹 하나의 설정."""

    name: str
    ip: str
    port: int
    iface: str = ""          # 로컬 인터페이스 IP (비우면 기본 인터페이스)
    ttl: int = 1
    enabled: bool = True

    # --- 직렬화 ----------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ip": self.ip,
            "port": self.port,
            "iface": self.iface,
            "ttl": self.ttl,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MulticastGroup":
        return cls(
            name=str(d.get("name", "")),
            ip=str(d.get("ip", "")),
            port=int(d.get("port", 0)),
            iface=str(d.get("iface", "")),
            ttl=int(d.get("ttl", 1)),
            enabled=bool(d.get("enabled", True)),
        )

    def validate(self) -> None:
        """유효하지 않으면 ValueError 를 던진다."""
        if not self.name or not self.ip:
            raise ValueError("이름과 그룹 IP는 필수입니다.")
        if not (0 < self.port < 65536):
            raise ValueError("포트는 1~65535 범위여야 합니다.")


@dataclass
class ReceivedMessage:
    """수신 메시지 1건."""

    group: str                       # 수신된 그룹 이름
    source: str                      # 송신자 "IP:port"
    text: str                        # 디코드된 본문 (바이너리는 hex)
    received_at: datetime = field(default_factory=datetime.now)

    @property
    def timestamp(self) -> str:
        return self.received_at.strftime("%H:%M:%S.%f")[:-3]
