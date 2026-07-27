"""멀티캐스트 엔진 (tkinter 비의존).

여러 그룹의 수신을 select() 기반 단일 스레드로 처리해 부하를 최소화한다.
수신 메시지는 thread-safe queue 로만 전달하고, GUI 는 그 큐를 폴링한다.
"""
from __future__ import annotations

import queue
import select
import socket
import threading
from typing import Iterable

from .models import MulticastGroup, ReceivedMessage
from .sockets import close_quietly, create_receiver, create_sender, decode_payload

RECV_BUF = 65535
SELECT_TIMEOUT = 1.0


class MulticastEngine:
    """멀티캐스트 소켓 수명주기 + 수신 루프를 관리한다."""

    def __init__(
        self, recv_queue: "queue.Queue[ReceivedMessage] | None" = None
    ) -> None:
        # 수신 메시지는 등록된 모든 구독 큐로 fan-out 된다.
        self._subscribers: list["queue.Queue[ReceivedMessage]"] = []
        if recv_queue is not None:
            self._subscribers.append(recv_queue)
        self._recv_socks: dict[str, socket.socket] = {}
        self._send_socks: dict[str, socket.socket] = {}
        self._groups: dict[str, MulticastGroup] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        # select 를 즉시 깨우기 위한 self-pipe (정지/변경 반영)
        self._wake_r, self._wake_w = socket.socketpair()

    def subscribe(self) -> "queue.Queue[ReceivedMessage]":
        """새 구독 큐를 만들어 등록하고 반환한다 (수신 탭·BAM 탭 각각 사용)."""
        q: "queue.Queue[ReceivedMessage]" = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def _publish(self, msg: ReceivedMessage) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(msg)

    # --- 수명주기 --------------------------------------------------------
    def start(self, groups: Iterable[MulticastGroup]) -> None:
        """활성 그룹들의 소켓을 열고 수신 스레드를 시작한다."""
        self.stop()
        with self._lock:
            for group in groups:
                if not group.enabled:
                    continue
                try:
                    self._recv_socks[group.name] = create_receiver(group)
                    self._send_socks[group.name] = create_sender(group)
                    self._groups[group.name] = group
                except OSError as exc:
                    self._publish(
                        ReceivedMessage(group.name, "", f"[소켓 오류] {exc}")
                    )
            self._running = True
        self._thread = threading.Thread(
            target=self._recv_loop, name="mcast-recv", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._wake()
            self._thread.join(timeout=2.0)
        with self._lock:
            for sock in (*self._recv_socks.values(), *self._send_socks.values()):
                close_quietly(sock)
            self._recv_socks.clear()
            self._send_socks.clear()
            self._groups.clear()
        self._thread = None

    # --- 수신 루프(단일 스레드) ------------------------------------------
    def _recv_loop(self) -> None:
        while self._running:
            with self._lock:
                items = list(self._recv_socks.items())
            rlist = [sock for _, sock in items] + [self._wake_r]
            try:
                ready, _, _ = select.select(rlist, [], [], SELECT_TIMEOUT)
            except (OSError, ValueError):
                continue
            for sock in ready:
                if sock is self._wake_r:
                    self._drain_wake()
                    continue
                self._read_one(sock, items)

    def _read_one(self, sock: socket.socket, items) -> None:
        name = next((n for n, s in items if s is sock), "?")
        try:
            data, addr = sock.recvfrom(RECV_BUF)
        except OSError:
            return
        self._publish(
            ReceivedMessage(name, f"{addr[0]}:{addr[1]}", decode_payload(data))
        )

    # --- 송신 -------------------------------------------------------------
    def send(self, name: str, message: str) -> None:
        with self._lock:
            sock = self._send_socks.get(name)
            group = self._groups.get(name)
        if sock is None or group is None:
            raise RuntimeError(f"'{name}' 그룹이 활성 상태가 아닙니다. 먼저 시작하세요.")
        sock.sendto(message.encode("utf-8"), (group.ip, group.port))

    # --- 조회 -------------------------------------------------------------
    def active_names(self) -> list[str]:
        with self._lock:
            return list(self._send_socks.keys())

    @property
    def running(self) -> bool:
        return self._running

    # --- self-pipe --------------------------------------------------------
    def _wake(self) -> None:
        try:
            self._wake_w.send(b"\x00")
        except OSError:
            pass

    def _drain_wake(self) -> None:
        try:
            self._wake_r.recv(1024)
        except OSError:
            pass
