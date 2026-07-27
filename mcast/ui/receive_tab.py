"""수신 메시지 탭.

수신 스레드가 넣어둔 큐를 GUI 스레드에서 after() 로 주기적으로 비워
그룹별로 표시한다. busy-loop 없이 부하를 낮춘다.
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from ..core import ReceivedMessage
from .widgets import LogView

ALL = "(전체)"
POLL_MS = 100            # 큐 폴링 주기
MAX_PER_TICK = 500       # 한 틱에 처리할 최대 건수 (GUI 반응성 유지)


class ReceiveTab(ttk.Frame):
    """그룹별 수신 로그 표시."""

    def __init__(self, master, recv_queue: "queue.Queue[ReceivedMessage]"):
        super().__init__(master)
        self._queue = recv_queue

        row = ttk.Frame(self)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Label(row, text="그룹 필터:").pack(side="left")
        self._filter = ttk.Combobox(row, state="readonly", width=20, values=[ALL])
        self._filter.set(ALL)
        self._filter.pack(side="left", padx=6)
        ttk.Button(row, text="지우기", command=lambda: self._log.clear()).pack(side="left")
        self._paused = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="일시정지", variable=self._paused).pack(side="left", padx=6)

        ttk.Label(self, text="수신 로그  (그룹별)").pack(anchor="w", padx=8)
        self._log = LogView(self)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

        self.after(POLL_MS, self._drain)

    def set_group_names(self, names: list[str]) -> None:
        current = self._filter.get()
        values = [ALL] + names
        self._filter["values"] = values
        if current not in values:
            self._filter.set(ALL)

    # --- 큐 폴링 ----------------------------------------------------------
    def _drain(self) -> None:
        if self._paused.get():
            self._trim_queue()
        else:
            flt = self._filter.get()
            for _ in range(MAX_PER_TICK):
                try:
                    msg = self._queue.get_nowait()
                except queue.Empty:
                    break
                if flt != ALL and flt != msg.group:
                    continue
                self._log.append(
                    f"[{msg.timestamp}] {msg.group} ← {msg.source}: {msg.text}"
                )
        self.after(POLL_MS, self._drain)

    def _trim_queue(self) -> None:
        # 일시정지 중 큐가 무한정 쌓이지 않도록 상한을 둔다.
        while self._queue.qsize() > 2000:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
