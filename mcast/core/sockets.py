"""멀티캐스트 소켓 생성 헬퍼 (tkinter 비의존).

수신/송신 소켓 생성 로직을 엔진에서 분리해 테스트·재사용을 쉽게 한다.
"""
from __future__ import annotations

import socket
import struct

from .models import MulticastGroup


def create_receiver(group: MulticastGroup) -> socket.socket:
    """그룹에 join 된 논블로킹 수신 소켓을 만든다."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    # VDR 이미지처럼 한 번에 수백 조각이 몰릴 때 커널 버퍼 오버플로 방지
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass

    sock.bind(("", group.port))

    iface_addr = (
        socket.inet_aton(group.iface)
        if group.iface.strip()
        else struct.pack("=I", socket.INADDR_ANY)
    )
    mreq = socket.inet_aton(group.ip) + iface_addr
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setblocking(False)
    return sock


def create_sender(group: MulticastGroup) -> socket.socket:
    """멀티캐스트 송신 소켓을 만든다."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, group.ttl)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    if group.iface.strip():
        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_MULTICAST_IF,
            socket.inet_aton(group.iface),
        )
    return sock


def decode_payload(data: bytes) -> str:
    """UTF-8 우선, 실패하면 hex 문자열로 표시한다."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.hex(" ")


def close_quietly(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass
