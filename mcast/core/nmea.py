"""NMEA / IEC 61162-450 저수준 처리 (tkinter 비의존, 순수함수).

- 체크섬 계산/검증
- 61162-450 datagram 분해: 전송헤더 + TAG 블록 + NMEA 문장
- TAG 블록 / 문장 파싱
- 송신용 datagram 조립 (체크섬 자동 계산)
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 61162-450 전송 헤더 (수신 예: b"UdPbC\x00")
PREFIX = b"UdPbC\x00"


# ---------------------------------------------------------------------------
# 체크섬
# ---------------------------------------------------------------------------
def checksum(body: str) -> int:
    """'$' 와 '*' 사이(또는 TAG '\\'와 '*' 사이) 문자열의 XOR."""
    x = 0
    for ch in body:
        x ^= ord(ch)
    return x


def checksum_hex(body: str) -> str:
    return f"{checksum(body):02X}"


# ---------------------------------------------------------------------------
# 수신 datagram 분해
# ---------------------------------------------------------------------------
@dataclass
class Datagram:
    prefix: str                       # 전송헤더 원문 (UdPbC + 제어문자)
    tag: dict[str, str]               # TAG 블록 {'g':..,'s':..,'n':..}
    tag_ok: bool                      # TAG 체크섬 일치 여부
    talker: str                       # 문장 talker (예: 'EI')
    formatter: str                    # 문장 formatter (예: 'ALF')
    fields: list[str]                 # 문장 필드 (formatter 포함, 0번=talker+formatter)
    sentence_ok: bool                 # 문장 체크섬 일치 여부
    raw: str = ""


def parse_datagram(raw: str) -> Datagram | None:
    """한 줄(문자열)을 전송헤더 + TAG + 문장으로 분해한다.

    형식: <prefix>\\<tag>*hh\\$<talker><formatter>,...*hh
    TAG 블록이 없는 순수 문장도 허용한다.
    """
    raw = raw.rstrip("\r\n")
    tag: dict[str, str] = {}
    tag_ok = True
    prefix = ""

    i = raw.find("\\")
    if i >= 0:
        j = raw.find("\\", i + 1)
        if j < 0:
            return None
        prefix = raw[:i]
        tag_str = raw[i + 1:j]              # "g:..*74"
        sentence = raw[j + 1:]
        tag, tag_ok = _parse_tag(tag_str)
    else:
        # TAG 없이 바로 문장인 경우
        k = raw.find("$")
        if k < 0:
            k = raw.find("!")
        if k < 0:
            return None
        prefix = raw[:k]
        sentence = raw[k:]

    parsed = _parse_sentence(sentence)
    if parsed is None:
        return None
    talker, formatter, fields, sentence_ok = parsed
    return Datagram(prefix, tag, tag_ok, talker, formatter, fields, sentence_ok, raw)


def _parse_tag(tag_str: str) -> tuple[dict[str, str], bool]:
    body, star, cks = tag_str.partition("*")
    ok = (not star) or (cks.upper() == checksum_hex(body))
    fields: dict[str, str] = {}
    for part in body.split(","):
        key, sep, val = part.partition(":")
        if sep:
            fields[key] = val
    return fields, ok


def _parse_sentence(sentence: str):
    s = sentence.strip()
    if s[:1] in ("$", "!"):
        s = s[1:]
    body, star, cks = s.partition("*")
    fields = body.split(",")
    if not fields or len(fields[0]) < 3:
        return None
    head = fields[0]
    talker, formatter = head[:2], head[2:]
    ok = (not star) or (cks.upper() == checksum_hex(body))
    return talker, formatter, fields, ok


# ---------------------------------------------------------------------------
# 송신 datagram 조립
# ---------------------------------------------------------------------------
def build_sentence(body: str) -> str:
    """'$'+body+'*'+체크섬. body 예: 'CAACN,105414.14,MRL,9025,81,A,C'."""
    return f"${body}*{checksum_hex(body)}"


def build_tag_block(body: str) -> str:
    """'\\'+body+'*'+체크섬+'\\'. body 예: 's:CA0001,d:EI0001,n:1,x:Nav,z:Nav'."""
    return f"\\{body}*{checksum_hex(body)}\\"


def build_datagram(tag_body: str, sentence_body: str,
                   prefix: bytes = PREFIX) -> bytes:
    """전송헤더 + TAG + 문장 + CRLF 를 raw 바이트로 만든다."""
    text = build_tag_block(tag_body) + build_sentence(sentence_body) + "\r\n"
    return prefix + text.encode("ascii")
