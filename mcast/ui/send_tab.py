"""송신 메시지 탭."""
from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from ..core import MulticastEngine, nmea
from .widgets import LogView


class SendTab(ttk.Frame):
    """활성 그룹을 골라 메시지를 송신한다."""

    def __init__(self, master, engine: MulticastEngine):
        super().__init__(master)
        self._engine = engine

        row = ttk.Frame(self)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Label(row, text="대상 그룹:").pack(side="left")
        self._group = ttk.Combobox(row, state="readonly", width=20, values=[])
        self._group.pack(side="left", padx=6)
        ttk.Button(row, text="목록 새로고침", command=self.refresh_groups).pack(side="left")

        opt = ttk.Frame(self)
        opt.pack(fill="x", padx=8, pady=(4, 0))
        self._udpbc = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt,
            text=r"UdPbC 헤더 (체크 시 'UdPbC\x00' + 입력값 + '\r\n' 으로 송신)",
            variable=self._udpbc,
        ).pack(side="left")

        msg = ttk.Frame(self)
        msg.pack(fill="x", padx=8, pady=4)
        ttk.Label(msg, text="메시지:").pack(side="left")
        self._msg = ttk.Entry(msg)
        self._msg.pack(side="left", fill="x", expand=True, padx=6)
        self._msg.bind("<Return>", lambda _e: self._send())
        ttk.Button(msg, text="송신", command=self._send).pack(side="left")

        ttk.Label(self, text="송신 로그").pack(anchor="w", padx=8)
        self._log = LogView(self)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

    def refresh_groups(self) -> None:
        names = self._engine.active_names()
        self._group["values"] = names
        if names and self._group.get() not in names:
            self._group.set(names[0])
        elif not names:
            self._group.set("")

    def _send(self) -> None:
        name = self._group.get()
        text = self._msg.get()
        if not name:
            messagebox.showinfo("알림", "대상 그룹을 선택하세요. (설정 탭에서 먼저 '시작')")
            return
        if not text:
            return
        # UdPbC 체크 시: 입력값 앞뒤로 전송헤더(UdPbC\x00)와 CRLF를 붙인다.
        # 입력값은 'UdPbC\x00' 와 '\r\n' 사이의 값(예: \TAG*cs\$문장*cs)만 넣는다.
        if self._udpbc.get():
            payload = nmea.PREFIX.decode("ascii") + text + "\r\n"
        else:
            payload = text
        try:
            self._engine.send(name, payload)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("송신 실패", str(exc))
            return
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log.append(f"[{ts}] → {name}: {payload!r}")
        self._msg.delete(0, "end")
