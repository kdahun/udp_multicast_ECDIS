"""HEX/바이너리 원시 데이터그램 송신 도메인 로직 (tkinter 비의존, 순수).

NMEA 문장이 아니라 '바이트열 그대로'를 UDP 멀티캐스트로 쏘기 위한 계층.

- parse_hex      : hex 문자열 → bytes (공백/줄바꿈/0x/구분자 허용)
- split_fixed    : 고정 크기 분할 (MTU 맞춤)
- split_marker   : 헤더 마커(예: UdPbC, RrUdP)가 나타날 때마다 새 조각으로 분할
- parse_hex_lines: 한 줄 = 데이터그램 1개

핵심 원칙: 한 조각이 곧 UDP 데이터그램 하나다. 조각을 이어 붙여 한 번에 보내면
수신측은 데이터그램 1개로 받는다 — 분할은 송신측에서 해야 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths

RAWSEND_CONFIG_PATH = paths.config_path("rawsend_config.json")

# 이더넷 MTU 1500 - IP 20 - UDP 8 = 1472. 넘으면 IP 단편화가 일어난다.
MTU_PAYLOAD = 1472
# macOS 기본 net.inet.udp.maxdgram. 넘으면 sendto 가 EMSGSIZE 로 실패한다.
MACOS_MAX_DGRAM = 9216
# UDP/IPv4 이론 최대 페이로드.
UDP_MAX_PAYLOAD = 65507

# hex 입력에서 무시할 구분 문자 (덤프 붙여넣기를 그대로 받기 위함)
_IGNORED = set(" \t\r\n:,-_|/")
_HEX_DIGITS = "0123456789abcdefABCDEF"


def parse_hex(text: str) -> bytes:
    """hex 문자열을 bytes 로 바꾼다.

    공백·줄바꿈·구분자(: , - _ | /)와 0x/\\x 접두사를 무시한다.
    hex 가 아닌 문자나 홀수 길이는 위치를 알려주는 ValueError 로 거른다.
    """
    digits: list[str] = []
    line, col = 1, 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        col += 1
        if ch == "\n":
            line, col = line + 1, 0
            i += 1
            continue
        if ch in _IGNORED:
            i += 1
            continue
        # 0x / 0X / \x 접두사는 건너뛴다
        if ch in "0\\" and i + 1 < n and text[i + 1] in "xX":
            i += 2
            col += 1
            continue
        if ch not in _HEX_DIGITS:
            raise ValueError(
                f"{line}행 {col}열의 '{ch}' 는 hex 문자가 아닙니다. "
                "0-9 a-f 와 공백/줄바꿈만 넣으세요."
            )
        digits.append(ch)
        i += 1

    if not digits:
        raise ValueError("hex 입력이 비어 있습니다.")
    if len(digits) % 2:
        raise ValueError(
            f"hex 자릿수가 {len(digits)}개로 홀수입니다. 1바이트 = 2자리이므로 "
            "짝수여야 합니다 (한 자리가 빠졌는지 확인하세요)."
        )
    return bytes.fromhex("".join(digits))


def parse_hex_lines(text: str) -> list[bytes]:
    """줄 단위로 파싱: 비어있지 않은 각 줄이 데이터그램 1개가 된다."""
    out: list[bytes] = []
    for no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            out.append(parse_hex(raw))
        except ValueError as exc:
            raise ValueError(f"{no}행: {exc}") from exc
    if not out:
        raise ValueError("hex 입력이 비어 있습니다.")
    return out


def split_fixed(data: bytes, size: int) -> list[bytes]:
    """size 바이트씩 자른다. 마지막 조각은 나머지 크기."""
    if size <= 0:
        raise ValueError("조각 크기는 1 이상이어야 합니다.")
    if not data:
        return []
    return [data[i:i + size] for i in range(0, len(data), size)]


def split_marker(data: bytes, marker: bytes) -> list[bytes]:
    """marker 가 나타나는 위치마다 새 조각을 시작한다.

    예: marker=b"UdPbC" 이고 데이터에 헤더가 3번 들어있으면 조각 3개.
    첫 marker 앞에 데이터가 있으면 그것도 별도 조각으로 둔다(앞쪽 쓰레기 확인용).
    """
    if not marker:
        raise ValueError("마커가 비어 있습니다.")
    if not data:
        return []
    starts: list[int] = []
    i = data.find(marker)
    while i != -1:
        starts.append(i)
        i = data.find(marker, i + 1)
    if not starts:
        raise ValueError(
            f"마커 {marker.hex()} 를 데이터에서 찾지 못했습니다. "
            "마커를 확인하거나 다른 분할 방식을 쓰세요."
        )
    out: list[bytes] = []
    if starts[0] > 0:
        out.append(data[:starts[0]])
    for start, end in zip(starts, starts[1:] + [len(data)]):
        out.append(data[start:end])
    return out


def describe(data: bytes, head: int = 16) -> str:
    """조각 앞부분을 hex + 인쇄가능 ASCII 로 요약한다 (헤더 눈으로 확인용)."""
    chunk = data[:head]
    hx = chunk.hex(" ")
    txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    tail = " …" if len(data) > head else ""
    return f"{hx}{tail}  |{txt}|"


def size_warnings(chunks: list[bytes]) -> list[str]:
    """조각 크기가 실무 한계를 넘는지 점검한다."""
    warns: list[str] = []
    over_mtu = [i + 1 for i, c in enumerate(chunks) if len(c) > MTU_PAYLOAD]
    over_dgram = [i + 1 for i, c in enumerate(chunks) if len(c) > MACOS_MAX_DGRAM]
    over_udp = [i + 1 for i, c in enumerate(chunks) if len(c) > UDP_MAX_PAYLOAD]
    if over_mtu:
        shown = ", ".join(f"#{n}" for n in over_mtu[:5])
        more = " …" if len(over_mtu) > 5 else ""
        warns.append(
            f"{len(over_mtu)}개 조각이 {MTU_PAYLOAD}B(MTU 1500 기준)를 넘습니다 "
            f"— IP 단편화가 일어나고, 조각 하나만 유실돼도 데이터그램 전체가 버려집니다. "
            f"({shown}{more})"
        )
    if over_dgram:
        warns.append(
            f"{len(over_dgram)}개 조각이 {MACOS_MAX_DGRAM}B 를 넘습니다 "
            "— macOS 기본 설정에서는 'Message too long' 으로 송신 실패합니다."
        )
    if over_udp:
        warns.append(
            f"{len(over_udp)}개 조각이 UDP 최대 {UDP_MAX_PAYLOAD}B 를 넘어 보낼 수 없습니다."
        )
    return warns


# ---------------------------------------------------------------------------
# 설정 영속화 (rawsend_config.json)
# ---------------------------------------------------------------------------
def default_config() -> dict:
    return {
        "ip": "239.192.0.1",
        "port": 60001,
        "iface": "",
        "ttl": 1,
        "mode": "fixed",          # none | fixed | lines | marker
        "chunk_size": MTU_PAYLOAD,
        "marker": "556450624300",   # 'UdPbC\x00' (61162-450 전송 헤더)
        "gap_ms": 5,
        "repeat": 1,
        "hex": "",
    }


def load_config(path=RAWSEND_CONFIG_PATH) -> dict:
    """설정 로드. 파일이 없거나 깨지면 기본값. 누락 키는 기본값으로 보충."""
    cfg = default_config()
    path = Path(path)
    if not path.exists():
        return cfg
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return cfg
    for k in cfg:
        if k in saved:
            cfg[k] = saved[k]
    return cfg


def save_config(cfg: dict, path=RAWSEND_CONFIG_PATH) -> None:
    Path(path).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
