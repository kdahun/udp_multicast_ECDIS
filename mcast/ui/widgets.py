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


class ScrollFrame(ttk.Frame):
    """세로 스크롤 되는 프레임. 내용은 .inner 에 배치한다.

    선박 목록처럼 항목 수가 가변이라 세로로 길어질 수 있는 영역에 쓴다.
    """

    def __init__(self, master):
        super().__init__(master)
        self._canvas = tk.Canvas(self, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self.inner = ttk.Frame(self._canvas)

        self._win = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(self._win, width=e.width),
        )
        self._canvas.configure(yscrollcommand=sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # 마우스 휠 (macOS/Windows: <MouseWheel>, Linux: Button-4/5)
        for seq, delta in (("<MouseWheel>", None), ("<Button-4>", -1), ("<Button-5>", 1)):
            self._canvas.bind_all(seq, self._on_wheel, add="+")

    def _on_wheel(self, event) -> None:
        if getattr(event, "num", None) == 4:
            self._canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
