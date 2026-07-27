"""VDR(RrUdP) 멀티캐스트 → PNG 이미지 복원 (tkinter 비의존).

- parse_packet   : RrUdP datagram 헤더 분해
- extract_png    : 이어붙인 버퍼에서 PNG(시그니처~IEND) 추출
- parse_meta     : VDRI/1.0 헤더(Source/Location/Time …) 파싱
- Reassembler    : 프레임ID별 조각 재조립 → VdrImage
- VdrReceiver    : 소켓 열고 스레드로 수신 → 큐에 VdrImage push
"""
from __future__ import annotations

import queue
import select
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths
from .models import MulticastGroup
from .sockets import close_quietly, create_receiver

PNG_SIG = b"\x89PNG\r\n\x1a\n"
IEND = b"IEND"
RECV_BUF = 65535
FRAME_TIMEOUT = 5.0

# 개발 실행: 저장소 루트 / 번들 실행: 사용자 데이터 폴더 아래 vdr_images/
OUT_DIR = paths.data_dir() / "vdr_images"


# ---------------------------------------------------------------------------
# 저수준 파싱
# ---------------------------------------------------------------------------
def parse_packet(data: bytes):
    """(frame_id, seq, total, payload) 또는 None(형식 불일치)."""
    if len(data) < 36 or data[:5] != b"RrUdP":
        return None
    hdr_len = int.from_bytes(data[8:10], "big")     # 보통 0x26 = 38
    frame_id = int.from_bytes(data[24:28], "big")
    seq = int.from_bytes(data[28:32], "big")
    total = int.from_bytes(data[32:36], "big")
    payload = data[hdr_len:] if 0 < hdr_len <= len(data) else data[38:]
    return frame_id, seq, total, payload


def extract_png(buf: bytes) -> bytes | None:
    start = buf.find(PNG_SIG)
    if start < 0:
        return None
    end = buf.find(IEND, start)
    if end < 0:
        return None
    return buf[start:end + 8]      # IEND(4) + CRC(4)


def png_dimensions(png: bytes) -> tuple[int, int]:
    if len(png) >= 24 and png[12:16] == b"IHDR":
        return (int.from_bytes(png[16:20], "big"),
                int.from_bytes(png[20:24], "big"))
    return (0, 0)


def parse_meta(buf: bytes) -> dict[str, str]:
    """VDRI/1.0 헤더를 {키:값} 으로. Content-Type 도 포함."""
    meta: dict[str, str] = {}
    i = buf.find(b"VDRI/")
    j = buf.find(PNG_SIG)
    if i >= 0 and j > i:
        text = buf[i:j].decode("latin-1", "replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if lines:
            meta["Version"] = lines[0].strip()
        for ln in lines[1:]:
            key, sep, val = ln.partition(":")
            if sep:
                meta[key.strip()] = val.strip()
    ct = buf.find(b"image/")
    if 0 <= ct and (i < 0 or ct < i):
        end = buf.find(b"\x00", ct)
        meta["Content-Type"] = buf[ct:end if end > 0 else ct + 16].decode("latin-1", "replace")
    return meta


# ---------------------------------------------------------------------------
# 완성 이미지
# ---------------------------------------------------------------------------
@dataclass
class VdrImage:
    png: bytes
    source: str                        # "192.168.0.122:60026"
    frame_id: int
    received_at: datetime
    meta: dict[str, str]
    width: int
    height: int
    n_parts: int
    packets: list[bytes]               # 원본 datagram 들 (원문용)

    @property
    def timestamp(self) -> str:
        return self.received_at.strftime("%H:%M:%S.%f")[:-3]

    @property
    def size_text(self) -> str:
        return f"{len(self.png) / 1024:.1f} KB"

    def default_name(self) -> str:
        loc = self.meta.get("Location", "").strip() or "vdr"
        ts = self.received_at.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return f"{loc}_{ts}.png"


def save_image(img: "VdrImage", out_dir=OUT_DIR) -> Path:
    """VdrImage 를 PNG 파일로 저장하고 경로를 반환한다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / img.default_name()
    path.write_bytes(img.png)
    return path


# ---------------------------------------------------------------------------
# 재조립
# ---------------------------------------------------------------------------
class Reassembler:
    def __init__(self) -> None:
        # frame_id -> {"parts": {seq: payload}, "raw": [datagram], "ts": float}
        self._frames: dict[int, dict] = {}

    def feed(self, data: bytes, source: str) -> VdrImage | None:
        parsed = parse_packet(data)
        if parsed is None:
            return None
        frame_id, seq, total, payload = parsed
        if not payload:                # 끝/keepalive 마커
            return None
        f = self._frames.setdefault(
            frame_id, {"parts": {}, "raw": [], "ts": 0.0})
        f["parts"][seq] = payload
        f["raw"].append(data)
        f["ts"] = _now()

        buf = b"".join(f["parts"][s] for s in sorted(f["parts"]))
        png = extract_png(buf)
        if png is None:
            return None
        w, h = png_dimensions(png)
        img = VdrImage(
            png=png, source=source, frame_id=frame_id,
            received_at=datetime.now(), meta=parse_meta(buf),
            width=w, height=h, n_parts=len(f["parts"]), packets=list(f["raw"]))
        del self._frames[frame_id]
        return img

    def sweep(self) -> None:
        now = _now()
        for fid in [k for k, v in self._frames.items()
                    if now - v["ts"] > FRAME_TIMEOUT]:
            del self._frames[fid]


def _now() -> float:
    from time import monotonic
    return monotonic()


# ---------------------------------------------------------------------------
# 수신기 (소켓 + 스레드)
# ---------------------------------------------------------------------------
class VdrReceiver:
    def __init__(self, out_queue: "queue.Queue[VdrImage]") -> None:
        self._queue = out_queue
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._asm = Reassembler()
        self._wake_r, self._wake_w = socket.socketpair()
        self.packets = 0        # 진단용: 지금까지 받은 RrUdP 패킷 수
        self.errors = 0         # 재조립 중 무시한 예외 수

    def start(self, ip: str, port: int, iface: str = "") -> None:
        self.stop()
        group = MulticastGroup(name="vdr", ip=ip, port=int(port), iface=iface)
        self._sock = create_receiver(group)       # OSError 는 호출측에서 처리
        self._asm = Reassembler()
        self.packets = 0
        self.errors = 0
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="vdr-recv", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            try:
                self._wake_w.send(b"\x00")
            except OSError:
                pass
            self._thread.join(timeout=2.0)
        close_quietly(self._sock)
        self._sock = None
        self._thread = None

    @property
    def running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        while self._running and self._sock is not None:
            try:
                ready, _, _ = select.select([self._sock, self._wake_r], [], [], 1.0)
            except (OSError, ValueError):
                break
            if not ready:
                self._asm.sweep()
                continue
            if self._wake_r in ready:
                try:
                    self._wake_r.recv(1024)
                except OSError:
                    pass
            if self._sock in ready:
                self._drain_socket()

    def _drain_socket(self) -> None:
        """깨어난 김에 커널 버퍼의 패킷을 모두 비운다(버스트 대응)."""
        while self._sock is not None:
            try:
                data, addr = self._sock.recvfrom(RECV_BUF)
            except (BlockingIOError, InterruptedError):
                return                     # 더 없음
            except OSError:
                return
            self.packets += 1
            try:
                img = self._asm.feed(data, f"{addr[0]}:{addr[1]}")
            except Exception:              # 한 패킷이 이상해도 스레드는 계속
                self.errors += 1
                continue
            if img is not None:
                self._queue.put(img)
