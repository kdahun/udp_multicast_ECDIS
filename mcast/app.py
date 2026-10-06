"""애플리케이션 조립: 노트북 + 3개 탭 + 엔진 배선."""
from __future__ import annotations

import os

# macOS 시스템 Tk 사용 시 나오는 DEPRECATION 경고 억제 (Tk() 생성 전에 설정)
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import tkinter as tk
from tkinter import ttk

from .core import MulticastEngine
from .ui import (
    AisTab, BamTab, ConfigTab, EpfsTab, HeadingTab, RadarTab, ReceiveTab,
    SdmeTab, SendTab, VdrTab,
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("UDP Multicast 송수신 툴")
        self.geometry("960x620")

        # 코어: 엔진. 수신 메시지는 구독 큐로 fan-out (수신 탭·BAM 탭 각각)
        self._engine = MulticastEngine()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        self.config_tab = ConfigTab(nb, self._engine, self._on_state_changed)
        self.send_tab = SendTab(nb, self._engine)
        self.receive_tab = ReceiveTab(nb, self._engine.subscribe())
        self.bam_tab = BamTab(nb, self._engine.subscribe())
        self.vdr_tab = VdrTab(nb)
        self.epfs_tab = EpfsTab(nb)
        self.heading_tab = HeadingTab(nb)
        self.sdme_tab = SdmeTab(nb)
        self.radar_tab = RadarTab(nb)
        self.ais_tab = AisTab(nb)

        nb.add(self.config_tab, text="UDP MULTICAST 설정")
        nb.add(self.send_tab, text="송신 메시지")
        nb.add(self.receive_tab, text="수신 메시지")
        nb.add(self.bam_tab, text="BAM")
        nb.add(self.vdr_tab, text="VDR")
        nb.add(self.epfs_tab, text="EPFS")
        nb.add(self.heading_tab, text="Heading")
        nb.add(self.sdme_tab, text="SDME")
        nb.add(self.radar_tab, text="Radar")
        nb.add(self.ais_tab, text="AIS")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bring_to_front()

    def _bring_to_front(self) -> None:
        """macOS에서 창이 터미널 뒤에 숨는 문제 방지: 앞으로 끌어오고 포커스."""
        self.update_idletasks()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _on_state_changed(self) -> None:
        """엔진 시작/정지 시 각 탭의 그룹 목록을 동기화한다."""
        names = self._engine.active_names()
        self.send_tab.refresh_groups()
        self.receive_tab.set_group_names(names)

    def _on_close(self) -> None:
        self._engine.stop()
        self.vdr_tab.shutdown()
        self.epfs_tab.shutdown()
        self.heading_tab.shutdown()
        self.sdme_tab.shutdown()
        self.radar_tab.shutdown()
        self.ais_tab.shutdown()
        self.destroy()


def main() -> None:
    App().mainloop()
