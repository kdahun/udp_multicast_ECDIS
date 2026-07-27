#!/usr/bin/env python3
"""VDR(RrUdP) 멀티캐스트 스트림에서 PNG 이미지를 복원한다.

VDR은 ECDIS 화면 캡처(PNG)를 'RrUdP' 프로토콜로 잘게 쪼개어 멀티캐스트로 보낸다.
이 스크립트는 조각들을 프레임 ID별로 모아 완성되면 PNG 파일로 저장한다.

사용법:
    python vdr_image.py VDR1                 # mc_config.json 의 그룹 이름
    python vdr_image.py 239.0.0.10 60000     # IP / 포트 직접 지정
    python vdr_image.py 239.0.0.10 60000 192.168.0.44   # 인터페이스 IP 추가

Ctrl+C 로 종료. 저장 위치: ./vdr_images/
"""
from __future__ import annotations

import os
import select
import sys
import time
from datetime import datetime

from mcast.core import MulticastGroup, load_groups
from mcast.core.sockets import close_quietly, create_receiver

PNG_SIG = b"\x89PNG\r\n\x1a\n"
IEND = b"IEND"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vdr_images")
FRAME_TIMEOUT = 5.0  # 이 시간 넘게 조각이 안 채워지면 폐기(초)


# ---------------------------------------------------------------------------
# RrUdP 패킷 파싱
# ---------------------------------------------------------------------------
def parse_packet(data: bytes):
    """(frame_id, seq, total, payload) 또는 None(형식 불일치)."""
    if len(data) < 36 or data[:5] != b"RrUdP":
        return None
    hdr_len = int.from_bytes(data[8:10], "big")   # 보통 0x26 = 38
    frame_id = int.from_bytes(data[24:28], "big")
    seq = int.from_bytes(data[28:32], "big")
    total = int.from_bytes(data[32:36], "big")
    payload = data[hdr_len:] if hdr_len <= len(data) else data[38:]
    return frame_id, seq, total, payload


def extract_png(buf: bytes) -> bytes | None:
    """이어붙인 버퍼에서 PNG 시그니처~IEND(+CRC) 구간을 잘라낸다."""
    start = buf.find(PNG_SIG)
    if start < 0:
        return None
    end = buf.find(IEND, start)
    if end < 0:
        return None
    return buf[start:end + 8]   # IEND(4) + CRC(4)


def parse_meta(buf: bytes) -> str:
    """VDRI/1.0 헤더에서 Source/Location/Time 등을 사람이 읽게 뽑는다."""
    i = buf.find(b"VDRI/")
    if i < 0:
        return ""
    j = buf.find(PNG_SIG, i)
    text = buf[i:j if j > 0 else i + 200].decode("latin-1", "replace")
    return " | ".join(line.strip() for line in text.splitlines() if line.strip())


# ---------------------------------------------------------------------------
# 조각 재조립
# ---------------------------------------------------------------------------
class Reassembler:
    def __init__(self) -> None:
        # frame_id -> {"total": int, "parts": {seq: payload}, "ts": float}
        self._frames: dict[int, dict] = {}
        os.makedirs(OUT_DIR, exist_ok=True)

    def feed(self, frame_id: int, seq: int, total: int, payload: bytes) -> None:
        if not payload:      # 끝/keepalive 마커는 데이터가 없다
            return
        frame = self._frames.setdefault(
            frame_id, {"total": 0, "parts": {}, "ts": time.time()}
        )
        if total:
            frame["total"] = total
        frame["parts"][seq] = payload
        frame["ts"] = time.time()

        buf = b"".join(frame["parts"][s] for s in sorted(frame["parts"]))
        png = extract_png(buf)   # IEND 까지 다 모였으면 반환
        if png is not None:
            self._save(frame_id, png, parse_meta(buf), len(frame["parts"]))
            del self._frames[frame_id]

    def _save(self, frame_id: int, png: bytes, meta: str, nparts: int) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = os.path.join(OUT_DIR, f"vdr_{ts}.png")
        with open(path, "wb") as fp:
            fp.write(png)
        size_kb = len(png) / 1024
        print(f"[저장] {path}  ({size_kb:.1f} KB, 조각 {nparts}개)")
        if meta:
            print(f"       {meta}")

    def sweep(self) -> None:
        now = time.time()
        stale = [fid for fid, f in self._frames.items()
                 if now - f["ts"] > FRAME_TIMEOUT]
        for fid in stale:
            del self._frames[fid]


# ---------------------------------------------------------------------------
# 그룹 결정 + 수신 루프
# ---------------------------------------------------------------------------
def resolve_group(argv: list[str]) -> MulticastGroup:
    if len(argv) >= 2 and argv[0].count(".") == 3:      # ip port [iface]
        ip, port = argv[0], int(argv[1])
        iface = argv[2] if len(argv) >= 3 else ""
        return MulticastGroup(name="cli", ip=ip, port=port, iface=iface)

    groups = {g.name: g for g in load_groups()}
    if len(argv) >= 1:                                  # 설정 그룹 이름
        if argv[0] in groups:
            return groups[argv[0]]
        sys.exit(f"'{argv[0]}' 그룹이 mc_config.json 에 없습니다. "
                 f"있는 그룹: {', '.join(groups) or '(없음)'}")
    if "VDR1" in groups:
        return groups["VDR1"]
    sys.exit("그룹을 지정하세요.  예) python vdr_image.py 239.0.0.10 60000")


def main() -> None:
    group = resolve_group(sys.argv[1:])
    sock = create_receiver(group)
    print(f"수신 대기: {group.ip}:{group.port}"
          f"{' iface=' + group.iface if group.iface else ''}  (Ctrl+C 종료)")
    print(f"저장 폴더: {OUT_DIR}\n")

    asm = Reassembler()
    try:
        while True:
            ready, _, _ = select.select([sock], [], [], 1.0)
            if not ready:
                asm.sweep()
                continue
            data, _addr = sock.recvfrom(65535)
            parsed = parse_packet(data)
            if parsed:
                asm.feed(*parsed)
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        close_quietly(sock)


if __name__ == "__main__":
    main()
