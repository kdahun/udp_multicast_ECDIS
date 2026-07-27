"""UDP MULTICAST 설정 탭."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from ..core import MulticastEngine, MulticastGroup, load_groups, save_groups

COLS = ("name", "ip", "port", "iface", "ttl", "enabled")
HEADERS = {
    "name": "이름", "ip": "그룹 IP", "port": "포트",
    "iface": "인터페이스IP", "ttl": "TTL", "enabled": "활성",
}
# 활성 칸 표시 문자열 (클릭하면 토글)
ENABLED_ON = "🟢 ON"
ENABLED_OFF = "⚪ OFF"
ENABLED_COL = f"#{len(COLS)}"          # 활성은 마지막 컬럼 → "#6"

# 텍스트 입력 폼에 넣는 필드(활성 제외)와 기본값
FORM_FIELDS = ("name", "ip", "port", "iface", "ttl")
DEFAULTS = {"name": "GROUP1", "ip": "239.0.0.1", "port": "5000",
            "iface": "", "ttl": "1"}


def _enabled_text(enabled: bool) -> str:
    return ENABLED_ON if enabled else ENABLED_OFF


def _is_enabled(text: str) -> bool:
    # 새 표기(ON/OFF) + 예전 저장값(Y/N) 모두 허용
    return str(text).strip() in (ENABLED_ON, "ON", "Y", "1", "True", "true")


class ConfigTab(ttk.Frame):
    """그룹 테이블 관리 + 엔진 시작/정지."""

    def __init__(
        self,
        master,
        engine: MulticastEngine,
        on_state_changed: Callable[[], None],
    ):
        super().__init__(master)
        self._engine = engine
        self._on_state_changed = on_state_changed

        self._build_table()
        self._build_form()
        self._build_buttons()
        self._load_saved()

    # --- 위젯 구성 --------------------------------------------------------
    def _build_table(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree = ttk.Treeview(top, columns=COLS, show="headings", height=12)
        for c in COLS:
            self.tree.heading(c, text=HEADERS[c])
            self.tree.column(c, width=120 if c != "enabled" else 80, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        sb.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        # 활성 칸 클릭 → 토글 / 그 외 더블클릭 → 폼으로 불러오기
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", self._on_row_dblclick)

    def _build_form(self) -> None:
        form = ttk.LabelFrame(self, text="그룹 추가 / 수정")
        form.pack(fill="x", padx=8, pady=4)
        self._entries: dict[str, ttk.Entry] = {}
        for i, c in enumerate(FORM_FIELDS):
            ttk.Label(form, text=HEADERS[c]).grid(row=0, column=i, padx=3, pady=2)
            entry = ttk.Entry(form, width=12)
            entry.insert(0, DEFAULTS[c])
            entry.grid(row=1, column=i, padx=3, pady=2)
            self._entries[c] = entry
        # 활성: 체크박스
        col = len(FORM_FIELDS)
        ttk.Label(form, text=HEADERS["enabled"]).grid(row=0, column=col, padx=3, pady=2)
        self._enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, variable=self._enabled_var).grid(row=1, column=col, padx=3, pady=2)

    def _build_buttons(self) -> None:
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8, pady=4)
        ttk.Button(btns, text="추가/수정", command=self._add_or_update).pack(side="left", padx=3)
        ttk.Button(btns, text="선택 삭제", command=self._delete_selected).pack(side="left", padx=3)
        ttk.Button(btns, text="설정 저장", command=self._save).pack(side="left", padx=3)

        run = ttk.Frame(self)
        run.pack(fill="x", padx=8, pady=4)
        self.btn_start = ttk.Button(run, text="▶ 시작", command=self._start)
        self.btn_start.pack(side="left", padx=3)
        self.btn_stop = ttk.Button(run, text="■ 정지", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=3)
        self.lbl_status = ttk.Label(run, text="상태: 정지됨", foreground="gray")
        self.lbl_status.pack(side="left", padx=10)

    # --- 테이블 <-> 모델 --------------------------------------------------
    def _row_values(self, g: MulticastGroup) -> tuple:
        return (g.name, g.ip, g.port, g.iface, g.ttl, _enabled_text(g.enabled))

    def groups(self) -> list[MulticastGroup]:
        result = []
        for iid in self.tree.get_children():
            name, ip, port, iface, ttl, enabled = self.tree.item(iid, "values")
            result.append(MulticastGroup(
                name=name, ip=ip, port=int(port), iface=iface,
                ttl=int(ttl or 1), enabled=_is_enabled(enabled),
            ))
        return result

    def _load_saved(self) -> None:
        for g in load_groups():
            self.tree.insert("", "end", values=self._row_values(g))

    def _persist(self) -> None:
        """현재 표 내용을 조용히 JSON 에 자동 저장한다."""
        try:
            save_groups(self.groups())
        except OSError:
            pass   # 저장 실패해도 앱 동작은 계속 (다음 변경 때 재시도)

    # --- 폼 / 토글 동작 ---------------------------------------------------
    def _on_tree_click(self, event) -> None:
        """활성 칸을 클릭하면 ON/OFF 를 토글한다."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != ENABLED_COL:
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        vals = list(self.tree.item(row, "values"))
        idx = COLS.index("enabled")
        vals[idx] = ENABLED_OFF if _is_enabled(vals[idx]) else ENABLED_ON
        self.tree.item(row, values=vals)
        self._persist()

    def _on_row_dblclick(self, _event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        vals = dict(zip(COLS, self.tree.item(sel[0], "values")))
        for c in FORM_FIELDS:
            self._entries[c].delete(0, "end")
            self._entries[c].insert(0, str(vals[c]))
        self._enabled_var.set(_is_enabled(vals["enabled"]))

    def _add_or_update(self) -> None:
        raw = {c: self._entries[c].get().strip() for c in FORM_FIELDS}
        try:
            g = MulticastGroup(
                name=raw["name"], ip=raw["ip"], port=int(raw["port"] or 0),
                iface=raw["iface"], ttl=int(raw["ttl"] or 1),
                enabled=self._enabled_var.get(),
            )
            g.validate()
        except ValueError as exc:
            messagebox.showwarning("입력 오류", str(exc))
            return

        for iid in self.tree.get_children():
            if self.tree.item(iid, "values")[0] == g.name:
                self.tree.item(iid, values=self._row_values(g))
                self._persist()
                return
        self.tree.insert("", "end", values=self._row_values(g))
        self._persist()

    def _delete_selected(self) -> None:
        for iid in self.tree.selection():
            self.tree.delete(iid)
        self._persist()

    def _save(self) -> None:
        try:
            save_groups(self.groups())
            messagebox.showinfo("저장 완료", "설정을 저장했습니다.")
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))

    # --- 시작/정지 --------------------------------------------------------
    def _start(self) -> None:
        groups = self.groups()
        if not groups:
            messagebox.showinfo("알림", "설정된 그룹이 없습니다.")
            return
        self._engine.start(groups)
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        active = ", ".join(self._engine.active_names()) or "(없음)"
        self.lbl_status.config(text=f"상태: 실행 중 · 활성: {active}", foreground="green")
        self._on_state_changed()

    def _stop(self) -> None:
        self._engine.stop()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.lbl_status.config(text="상태: 정지됨", foreground="gray")
        self._on_state_changed()
