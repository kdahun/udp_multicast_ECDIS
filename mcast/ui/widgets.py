"""재사용 UI 위젯."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

MAX_LOG_LINES = 2000


class LogView(ttk.Frame):
    """자동 스크롤 + 라인 수 상한이 있는 읽기전용 로그 창.

    라인 수를 제한해 장시간 구동 시 메모리 증가를 막는다.
    """

    def __init__(self, master, max_lines: int = MAX_LOG_LINES, height: int = 10):
        super().__init__(master)
        self._max_lines = max_lines

        self._text = tk.Text(self, wrap="none", height=height, state="disabled")
        self._text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        sb.pack(side="left", fill="y")
        self._text.configure(yscrollcommand=sb.set)

    def append(self, line: str) -> None:
        self._text.configure(state="normal")
        self._text.insert("end", line + "\n")
        line_count = int(self._text.index("end-1c").split(".")[0])
        if line_count > self._max_lines:
            self._text.delete("1.0", f"{line_count - self._max_lines}.0")
        self._text.see("end")
        self._text.configure(state="disabled")

    def clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
