"""사용자공임 산출 계산기(M/H적용) - Windows 데스크톱 버전.

index.html 과 동일한 계산 로직(반올림 시점 포함)을 tkinter GUI로 구현.
"""
from __future__ import annotations

import json
import os
import tkinter as tk
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from tkinter import ttk

__version__ = "1.3.0"

INK = "#1c2b26"
PAPER = "#f6f4ee"
LINE = "#c9c2b2"
ACCENT = "#2f5d50"
ACCENT_SOFT = "#dde7e2"
NUM = "#3d3226"
MUTED = "#6b6255"


def to_num(text: str) -> float:
    text = (text or "").replace(",", "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def fmt_won(n: float) -> str:
    return f"{round(n):,}원"


def fmt_num(n: float, digits: int) -> str:
    return f"{n:,.{digits}f}"


def format_amount(text: str) -> str:
    """입력 문자열에서 숫자/소수점만 남기고 정수부에 천단위 콤마를 넣는다."""
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    int_part, dot, frac = cleaned.partition(".")
    frac = frac.replace(".", "")
    if not int_part and not dot:
        return ""
    int_text = f"{int(int_part):,}" if int_part else "0"
    return int_text + (dot + frac if dot else "")


VAT_RATE = 1.1  # 부가가치세 10% 기준


def _settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "UserLaborCalculator" / "settings.json"


def load_settings() -> dict:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data: dict) -> None:
    # 마지막 입력값 저장은 편의 기능이라, 저장 실패가 계산을 막으면 안 된다.
    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def fit_to_content(win: tk.Misc, min_width: int = 0):
    # 실제 렌더링된 위젯 크기에 맞춰 창 크기를 자동 산정한다.
    # DPI/폰트에 따라 요구 높이가 달라지므로 고정 geometry를 쓰면 내용이 잘릴 수 있다.
    win.update_idletasks()
    width = max(win.winfo_reqwidth(), min_width)
    height = win.winfo_reqheight()
    win.geometry(f"{width}x{height}")
    win.minsize(width, height)


class BasicCalculator:
    """사칙연산 기본 계산기 (마우스 + 키보드). Decimal 기반이라 0.1+0.2 같은 오차가 없다."""

    MAX_DIGITS = 15
    OP_SYMBOL = {"+": "+", "-": "−", "*": "×", "/": "÷"}

    def __init__(self, win: tk.Toplevel):
        self.win = win
        self.acc: Decimal | None = None
        self.op: str | None = None
        self.cur = "0"
        self.new_entry = True        # 다음 숫자 입력이 새 숫자로 시작되어야 하는지
        self.expect_operand = False  # 연산자를 누른 직후 아직 피연산자를 입력하지 않았는지
        self.error = False
        self.expr_text = ""
        self._build()
        self._refresh()

    # ---- UI ----
    def _build(self):
        win = self.win
        win.configure(bg=PAPER)
        win.resizable(False, False)

        disp = tk.Frame(win, bg=INK)
        disp.pack(fill="x", padx=12, pady=(12, 8))
        self.expr_label = tk.Label(disp, text="", bg=INK, fg="#a9c2b8",
                                    font=("Consolas", 10), anchor="e")
        self.expr_label.pack(fill="x", padx=10, pady=(8, 0))
        # 읽기전용 Entry: 클릭하면 키보드 포커스를 받고, 선택/Ctrl+C 복사/Ctrl+V 붙여넣기 가능
        self.value_var = tk.StringVar(value="0")
        self.value_entry = tk.Entry(
            disp, textvariable=self.value_var, state="readonly",
            readonlybackground=INK, fg=PAPER, justify="right", bd=0,
            highlightthickness=0, width=1, font=("Consolas", 24, "bold"),
        )
        self.value_entry.pack(fill="x", padx=10, pady=(0, 8))
        self.value_entry.bind("<<Paste>>", self._on_paste)

        pad = tk.Frame(win, bg=PAPER)
        pad.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        for c in range(4):
            pad.columnconfigure(c, weight=1, uniform="col")

        # (표시문자, 종류, 인자)
        layout = [
            [("C", "clear", ""), ("←", "back", ""), ("%", "pct", ""), ("÷", "op", "/")],
            [("7", "digit", "7"), ("8", "digit", "8"), ("9", "digit", "9"), ("×", "op", "*")],
            [("4", "digit", "4"), ("5", "digit", "5"), ("6", "digit", "6"), ("−", "op", "-")],
            [("1", "digit", "1"), ("2", "digit", "2"), ("3", "digit", "3"), ("+", "op", "+")],
            [("±", "neg", ""), ("0", "digit", "0"), (".", "dot", ""), ("=", "eq", "")],
        ]
        actions = {
            "clear": lambda a: self.clear(),
            "back": lambda a: self.backspace(),
            "pct": lambda a: self.percent(),
            "op": lambda a: self.operator(a),
            "digit": lambda a: self.digit(a),
            "neg": lambda a: self.negate(),
            "dot": lambda a: self.dot(),
            "eq": lambda a: self.equals(),
        }
        for r, row in enumerate(layout):
            for c, (text, kind, arg) in enumerate(row):
                if kind == "eq":
                    bg, fg, abg = ACCENT, "white", "#244a40"
                elif kind in ("op", "clear", "back", "pct"):
                    bg, fg, abg = ACCENT_SOFT, ACCENT, "#cbdad3"
                else:
                    bg, fg, abg = "#fffdf9", NUM, "#efece3"
                btn = tk.Button(
                    pad, text=text, bg=bg, fg=fg, activebackground=abg,
                    font=("Malgun Gothic", 12, "bold"), relief="flat", bd=0,
                    highlightthickness=1, highlightbackground=LINE, cursor="hand2",
                    command=lambda k=kind, a=arg: self._press(actions[k], a),
                )
                btn.grid(row=r, column=c, sticky="nsew", padx=2, pady=2, ipady=8)

        tk.Label(win, text="키보드로도 입력됩니다 · Enter 계산 · Esc 초기화 · Ctrl+V 붙여넣기",
                 bg=PAPER, fg="#a39c8c", font=("Malgun Gothic", 8)).pack(pady=(0, 10))

        win.bind("<Key>", self._on_key)

    def _press(self, action, arg):
        action(arg)
        # 버튼을 클릭해도 키보드 포커스는 항상 표시창에 유지한다.
        self.value_entry.focus_set()

    def focus_input(self):
        self.value_entry.focus_set()

    def _on_paste(self, _event=None):
        try:
            text = self.win.clipboard_get()
        except tk.TclError:
            return "break"
        cleaned = text.strip().replace(",", "").replace(" ", "")
        try:
            d = Decimal(cleaned)
        except InvalidOperation:
            return "break"
        if not d.is_finite():
            return "break"
        s = self._dec_to_str(d)
        if sum(ch.isdigit() for ch in s) > self.MAX_DIGITS:
            return "break"
        self._reset_if_error()
        self.cur = s
        self.new_entry = False
        self.expect_operand = False
        self._refresh()
        return "break"

    def _on_key(self, event):
        ch, ks = event.char, event.keysym
        if ch and ch in "0123456789":
            self.digit(ch)
        elif ch in (".",):
            self.dot()
        elif ch in ("+", "-", "*", "/"):
            self.operator(ch)
        elif ch == "%":
            self.percent()
        elif ch == "=" or ks in ("Return", "KP_Enter"):
            self.equals()
        elif ks == "BackSpace":
            self.backspace()
        elif ks in ("Escape", "Delete"):
            self.clear()

    # ---- 표시 ----
    @staticmethod
    def _with_commas(text: str) -> str:
        sign = "-" if text.startswith("-") else ""
        body = text.lstrip("-")
        int_part, dot, frac = body.partition(".")
        return f"{sign}{int(int_part or '0'):,}{dot}{frac}"

    @staticmethod
    def _dec_to_str(d: Decimal) -> str:
        s = format(d.normalize(), "f")
        return "0" if s == "-0" else s

    def _refresh(self):
        text = "0으로 나눌 수 없습니다" if self.error else self._with_commas(self.cur)
        n = len(text)
        size = 24 if n <= 12 else (18 if n <= 16 else 14)
        if self.error:
            size = 12
        self.value_var.set(text)
        self.value_entry.config(font=("Consolas", size, "bold"))
        self.expr_label.config(text=self.expr_text)

    # ---- 동작 ----
    def _reset_if_error(self):
        if self.error:
            self.clear()

    def clear(self):
        self.acc = None
        self.op = None
        self.cur = "0"
        self.new_entry = True
        self.expect_operand = False
        self.error = False
        self.expr_text = ""
        self._refresh()

    def digit(self, d: str):
        self._reset_if_error()
        if self.new_entry:
            self.cur = d
            self.new_entry = False
        else:
            digits = sum(ch.isdigit() for ch in self.cur)
            if digits >= self.MAX_DIGITS:
                return
            if self.cur == "0":
                self.cur = d
            elif self.cur == "-0":
                self.cur = "-" + d
            else:
                self.cur += d
        self.expect_operand = False
        self._refresh()

    def dot(self):
        self._reset_if_error()
        if self.new_entry:
            self.cur = "0."
            self.new_entry = False
        elif "." not in self.cur:
            self.cur += "."
        self.expect_operand = False
        self._refresh()

    def backspace(self):
        self._reset_if_error()
        if self.new_entry:
            return
        self.cur = self.cur[:-1]
        if self.cur in ("", "-"):
            self.cur = "0"
        self._refresh()

    def negate(self):
        if self.error:
            return
        if self.cur.startswith("-"):
            self.cur = self.cur[1:]
        elif self.cur != "0":
            self.cur = "-" + self.cur
        self.expect_operand = False
        self._refresh()

    def percent(self):
        if self.error:
            return
        value = Decimal(self.cur)
        with localcontext() as ctx:
            ctx.prec = 15
            if self.acc is not None and self.op in ("+", "-"):
                value = self.acc * value / 100
            else:
                value = value / 100
        self.cur = self._dec_to_str(value)
        self.new_entry = True
        self.expect_operand = False
        self._refresh()

    def _compute(self, a: Decimal, op: str, b: Decimal) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 15
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if b == 0:
                raise ZeroDivisionError
            return a / b

    def _fail(self):
        self.error = True
        self.acc = None
        self.op = None
        self.expr_text = ""
        self.new_entry = True
        self.expect_operand = False
        self._refresh()

    def operator(self, op: str):
        if self.error:
            return
        value = Decimal(self.cur)
        if self.op is not None and self.expect_operand:
            pass  # 연산자만 바꾸는 경우
        elif self.op is not None and self.acc is not None:
            try:
                self.acc = self._compute(self.acc, self.op, value)
            except ZeroDivisionError:
                self._fail()
                return
            self.cur = self._dec_to_str(self.acc)
        else:
            self.acc = value
        self.op = op
        self.expect_operand = True
        self.new_entry = True
        self.expr_text = f"{self._with_commas(self._dec_to_str(self.acc))} {self.OP_SYMBOL[op]}"
        self._refresh()

    def equals(self):
        if self.error or self.op is None or self.acc is None:
            self.new_entry = True
            return
        value = Decimal(self.cur)
        left, op = self.acc, self.op
        try:
            result = self._compute(left, op, value)
        except ZeroDivisionError:
            self._fail()
            return
        self.expr_text = (f"{self._with_commas(self._dec_to_str(left))} {self.OP_SYMBOL[op]} "
                          f"{self._with_commas(self._dec_to_str(value))} =")
        self.cur = self._dec_to_str(result)
        self.acc = None
        self.op = None
        self.new_entry = True
        self.expect_operand = False
        self._refresh()


class LaborCalculatorApp:
    CARD_BG = "#fffdf9"
    MEMO_COUNT = 6
    MEMO_COLS = 3
    MEMO_MAX = 50
    DEFAULT_TIMES = ["1.55", "0.5"]

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"사용자공임 산출 계산기(M/H적용) v{__version__}")
        root.configure(bg=PAPER)

        self.settings = load_settings()
        self._calc_win: tk.Toplevel | None = None
        self._ready = False
        self.time_rows: list[tuple[tk.Frame, tk.StringVar]] = []
        self.memo_boxes: list[tk.Text] = []

        self._build_style()
        self._build_header()
        self._build_section1()
        self._build_section_vat()
        self._build_section_memo()

        self._ready = True
        self.calculate()
        self._fit_to_content()

    def _fit_to_content(self):
        fit_to_content(self.root, min_width=560)

    def _saved(self, key: str) -> dict:
        value = self.settings.get(key)
        return value if isinstance(value, dict) else {}

    # ---- 스타일/공통 ----
    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    def _section_title(self, text: str, hint: str = ""):
        row = tk.Frame(self.root, bg=PAPER)
        row.pack(fill="x", padx=16, pady=(8, 4))
        tk.Label(row, text=text, bg=PAPER, fg=INK,
                  font=("Malgun Gothic", 11, "bold")).pack(side="left")
        if hint:
            tk.Label(row, text=hint, bg=PAPER, fg="#a39c8c",
                      font=("Malgun Gothic", 8)).pack(side="left", padx=(10, 0), pady=(3, 0))

    def _card(self, parent, step_label: str, title: str):
        outer = tk.Frame(parent, bg=PAPER)
        badge = tk.Label(
            outer, text=step_label, bg=ACCENT, fg="white",
            font=("Consolas", 8, "bold"), padx=6, pady=1,
        )
        badge.pack(anchor="w")

        card = tk.Frame(outer, bg=self.CARD_BG, highlightbackground=LINE,
                         highlightthickness=1, bd=0)
        card.pack(fill="both", expand=True)

        inner = tk.Frame(card, bg=self.CARD_BG, padx=10, pady=6)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text=title, bg=self.CARD_BG, fg=ACCENT,
                  font=("Malgun Gothic", 9, "bold")).pack(anchor="w", pady=(0, 4))
        return outer, inner

    def _labeled_entry(self, parent, label_text: str, var: tk.StringVar, unit: str):
        row = tk.Frame(parent, bg=self.CARD_BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label_text, bg=self.CARD_BG, fg=MUTED,
                  font=("Malgun Gothic", 9), width=7, anchor="w").pack(side="left")
        entry = tk.Entry(row, textvariable=var, justify="right", width=10,
                          font=("Consolas", 10), fg=NUM,
                          relief="solid", bd=1, highlightthickness=0)
        entry.pack(side="left", ipady=2)
        entry.bind("<KeyRelease>", lambda e: self.calculate())
        tk.Label(row, text=unit, bg=self.CARD_BG, fg="#a39c8c",
                  font=("Malgun Gothic", 9), width=2).pack(side="left")
        return entry

    # ---- 헤더 ----
    def _build_header(self):
        head = tk.Frame(self.root, bg=PAPER)
        head.pack(fill="x", padx=16, pady=(12, 4))

        top_row = tk.Frame(head, bg=PAPER)
        top_row.pack(fill="x")

        title_box = tk.Frame(top_row, bg=PAPER)
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(title_box, text="사용자공임 산출 계산기", bg=PAPER, fg=INK,
                  font=("Georgia", 15, "bold")).pack(anchor="w")
        tk.Label(title_box, text="M/H(시간당 공임단가)를 적용해 사용자공임 최종 금액을 계산합니다",
                  bg=PAPER, fg=MUTED, font=("Malgun Gothic", 8)).pack(anchor="w", pady=(2, 0))

        tk.Button(
            top_row, text="계산기", command=self._open_basic_calculator,
            bg=self.CARD_BG, fg=ACCENT, relief="solid", bd=1,
            font=("Malgun Gothic", 8, "bold"), highlightbackground=LINE,
            cursor="hand2",
        ).pack(side="right", anchor="n", ipadx=4, ipady=2)

        tk.Frame(head, bg=LINE, height=1).pack(fill="x", pady=(8, 0))

    # ---- 1. 시간당 공임단가 및 최종 결과값 ----
    def _build_section1(self):
        self._section_title("1. 시간당 공임단가 및 최종 결과값")
        saved = self._saved("main")

        def var(key: str, default: str) -> tk.StringVar:
            return tk.StringVar(value=str(saved.get(key, default)))

        self.base_amount_var = var("base_amount", "61,210")
        self.base_hour_var = var("base_hour", "1.580")
        self.ref_amount_var = var("ref_amount", "56,200")
        self.rate_var = var("rate", "65")
        times = saved.get("times")
        if not isinstance(times, list) or not times:
            times = self.DEFAULT_TIMES

        wrap = tk.Frame(self.root, bg=PAPER)
        wrap.pack(fill="x", padx=16)
        wrap.columnconfigure(0, weight=1, uniform="step")
        wrap.columnconfigure(1, weight=1, uniform="step")

        # STEP 1 (좌)
        outer1, inner1 = self._card(wrap, "STEP 1", "M/H 계산 — 시간당 공임단가")
        outer1.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._labeled_entry(inner1, "공임금액", self.base_amount_var, "원")
        self._labeled_entry(inner1, "시간", self.base_hour_var, "H")
        strip = tk.Frame(inner1, bg=ACCENT_SOFT)
        strip.pack(fill="x", pady=(6, 0))
        pad = tk.Frame(strip, bg=ACCENT_SOFT)
        pad.pack(fill="x", padx=8, pady=5)
        tk.Label(pad, text="H단가 = 공임금액 ÷ 시간", bg=ACCENT_SOFT, fg=ACCENT,
                  font=("Consolas", 8)).pack(anchor="w")
        self.h_rate_label = tk.Label(pad, text="-", bg=ACCENT_SOFT, fg=ACCENT,
                                      font=("Consolas", 11, "bold"))
        self.h_rate_label.pack(anchor="e")

        # STEP 2 (우)
        outer2, inner2 = self._card(wrap, "STEP 2", "최종 결과값 계산")
        outer2.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ref_entry = self._labeled_entry(inner2, "기준금액", self.ref_amount_var, "원")
        self.time_list_frame = tk.Frame(inner2, bg=self.CARD_BG)
        self.time_list_frame.pack(fill="x")
        self._build_add_time_button(inner2, ref_entry)
        self._labeled_entry(inner2, "적용율", self.rate_var, "%")

        self._build_result()
        for t in times:
            self._add_time_row(str(t))

    def _build_add_time_button(self, parent, ref_entry: tk.Entry):
        # 같은 카드의 입력칸과 위치·크기를 맞춘다(라벨 열 + 입력칸과 같은 폭/높이).
        parent.update_idletasks()
        # 입력칸은 ipady=2로 배치되므로 실제 높이는 요청 높이 + 4
        w, h = ref_entry.winfo_reqwidth(), ref_entry.winfo_reqheight() + 4
        row = tk.Frame(parent, bg=self.CARD_BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="", bg=self.CARD_BG, font=("Malgun Gothic", 9),
                  width=7).pack(side="left")
        box = tk.Frame(row, width=w, height=h, bg=self.CARD_BG)
        box.pack(side="left")
        box.pack_propagate(False)
        tk.Button(
            box, text="+ 시간 추가", command=lambda: self._add_time_row("0"),
            bg=self.CARD_BG, fg=ACCENT, relief="solid", bd=1,
            font=("Malgun Gothic", 8), highlightbackground=LINE, cursor="hand2",
        ).pack(fill="both", expand=True)

    def _add_time_row(self, value: str):
        row = tk.Frame(self.time_list_frame, bg=self.CARD_BG)
        row.pack(fill="x", pady=2)

        tk.Label(row, text="", bg=self.CARD_BG, fg=MUTED,
                  font=("Malgun Gothic", 9), width=7, anchor="w").pack(side="left")
        var = tk.StringVar(value=value)
        entry = tk.Entry(row, textvariable=var, justify="right", width=10,
                          font=("Consolas", 10), fg=NUM, relief="solid", bd=1)
        entry.pack(side="left", ipady=2)
        entry.bind("<KeyRelease>", lambda e: self.calculate())
        tk.Label(row, text="H", bg=self.CARD_BG, fg="#a39c8c",
                  font=("Malgun Gothic", 9)).pack(side="left", padx=(4, 0))
        tk.Button(
            row, text="×", command=lambda: self._remove_time_row(row),
            bg=self.CARD_BG, fg="#a39c8c", relief="flat", bd=0,
            font=("Malgun Gothic", 11), cursor="hand2",
        ).pack(side="left")

        self.time_rows.append((row, var))
        self._relabel_time_rows()
        self.calculate()
        if self._ready:
            self._fit_to_content()

    def _remove_time_row(self, row: tk.Frame):
        if len(self.time_rows) <= 1:
            return
        self.time_rows = [(r, v) for (r, v) in self.time_rows if r is not row]
        row.destroy()
        self._relabel_time_rows()
        self.calculate()
        self._fit_to_content()

    def _relabel_time_rows(self):
        for i, (row, _var) in enumerate(self.time_rows):
            row.winfo_children()[0].config(text="시간(H)" if i == 0 else "")

    def _build_result(self):
        outer = tk.Frame(self.root, bg=PAPER)
        outer.pack(fill="x", padx=16, pady=(8, 0))
        card = tk.Frame(outer, bg=INK)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=INK, padx=14, pady=8)
        inner.pack(fill="x")

        left = tk.Frame(inner, bg=INK)
        left.pack(side="left")
        tk.Label(left, text="최종 결과값", bg=INK, fg="#a9c2b8",
                  font=("Malgun Gothic", 8)).pack(anchor="w")
        self.final_label = tk.Label(left, text="0원", bg=INK, fg=PAPER,
                                     font=("Georgia", 22, "bold"))
        self.final_label.pack(anchor="w")
        tk.Frame(left, width=190, height=1, bg=INK).pack()

        tk.Frame(inner, bg="#3a493f", width=1).pack(side="left", fill="y", padx=14)

        grid = tk.Frame(inner, bg=INK)
        grid.pack(side="left", fill="x", expand=True)
        for i in range(2):
            grid.columnconfigure(i, weight=1, uniform="bd")

        self.breakdown_labels = {}
        specs = [("h_rate", "H단가"), ("total_h", "총 H"),
                 ("sum", "공임합계"), ("rate", "적용율")]
        for idx, (key, label_text) in enumerate(specs):
            r, c = divmod(idx, 2)
            cell = tk.Frame(grid, bg=INK)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 10), pady=1)
            tk.Label(cell, text=label_text, bg=INK, fg="#7f9187",
                      font=("Malgun Gothic", 8)).pack(anchor="w")
            val = tk.Label(cell, text="-", bg=INK, fg="#c9d6cd",
                            font=("Consolas", 10, "bold"))
            val.pack(anchor="w")
            self.breakdown_labels[key] = val

    # ---- 2. VAT 계산기 (본문 내장) ----
    def _build_section_vat(self):
        self._section_title("2. VAT 계산기", "한쪽에 금액을 입력하면 반대쪽이 자동 계산됩니다 (부가세 10%)")
        outer = tk.Frame(self.root, bg=self.CARD_BG, highlightbackground=LINE, highlightthickness=1)
        outer.pack(fill="x", padx=16)
        inner = tk.Frame(outer, bg=self.CARD_BG, padx=10, pady=8)
        inner.pack(fill="x")
        inner.columnconfigure(0, weight=1, uniform="vat")
        inner.columnconfigure(1, weight=1, uniform="vat")

        saved = self._saved("vat")
        supply_var = tk.StringVar(value=format_amount(str(saved.get("supply", ""))))
        vat_total_var = tk.StringVar(value=format_amount(str(saved.get("vat_total", ""))))
        updating = {"flag": False}

        def persist():
            self.settings["vat"] = {"supply": supply_var.get(), "vat_total": vat_total_var.get()}
            save_settings(self.settings)

        def make_cell(col: int, label_text: str, var: tk.StringVar) -> tk.Entry:
            cell = tk.Frame(inner, bg=self.CARD_BG)
            cell.grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 8, 0))
            tk.Label(cell, text=label_text, bg=self.CARD_BG, fg=MUTED,
                      font=("Malgun Gothic", 9)).pack(side="left", padx=(0, 6))
            entry = tk.Entry(cell, textvariable=var, justify="right", width=11,
                              font=("Consolas", 10), fg=NUM, relief="solid", bd=1)
            entry.pack(side="left", ipady=2)
            tk.Label(cell, text="원", bg=self.CARD_BG, fg="#a39c8c",
                      font=("Malgun Gothic", 9)).pack(side="left", padx=(3, 0))
            btn = tk.Button(
                cell, text="복사", bg=self.CARD_BG, fg=ACCENT, relief="solid", bd=1,
                font=("Malgun Gothic", 8), cursor="hand2",
            )
            btn.config(command=lambda: self._copy_to_clipboard(var, btn))
            btn.pack(side="left", padx=(5, 0))
            return entry

        vat_entry = make_cell(0, "VAT 합산금액", vat_total_var)
        supply_entry = make_cell(1, "공급가액", supply_var)

        def reformat(var: tk.StringVar, entry: tk.Entry):
            # 키 입력이 끝난 뒤(커서 위치가 확정된 시점)에 천단위 콤마를 넣고,
            # 커서는 같은 숫자 뒤에 유지한다. 상대 칸 값은 이미 계산돼 있으므로 재계산하지 않는다.
            text = var.get()
            new = format_amount(text)
            if new == text:
                return
            pos = entry.index("insert")
            keep = sum(1 for ch in text[:pos] if ch.isdigit() or ch == ".")
            updating["flag"] = True
            try:
                var.set(new)
            finally:
                updating["flag"] = False
            new_pos, count = 0, 0
            while new_pos < len(new) and count < keep:
                if new[new_pos].isdigit() or new[new_pos] == ".":
                    count += 1
                new_pos += 1
            entry.icursor(new_pos)
            persist()

        for var, entry in ((supply_var, supply_entry), (vat_total_var, vat_entry)):
            entry.bind("<KeyRelease>", lambda e, v=var, en=entry: reformat(v, en))
            for seq in ("<<Paste>>", "<<Cut>>"):
                entry.bind(seq, lambda e, v=var, en=entry: en.after_idle(reformat, v, en), add="+")

        def on_supply_change(*_args):
            if updating["flag"]:
                return
            updating["flag"] = True
            try:
                text = supply_var.get().strip()
                vat_total_var.set(f"{round(to_num(text) * VAT_RATE):,}" if text else "")
            finally:
                updating["flag"] = False
            persist()

        def on_vat_change(*_args):
            if updating["flag"]:
                return
            updating["flag"] = True
            try:
                text = vat_total_var.get().strip()
                supply_var.set(f"{round(to_num(text) / VAT_RATE):,}" if text else "")
            finally:
                updating["flag"] = False
            persist()

        supply_var.trace_add("write", on_supply_change)
        vat_total_var.trace_add("write", on_vat_change)

    # ---- 3. 메모장 ----
    def _build_section_memo(self):
        self._section_title("3. 메모장", f"칸을 클릭하면 내용이 복사됩니다 · 칸당 최대 {self.MEMO_MAX}자")
        grid = tk.Frame(self.root, bg=PAPER)
        grid.pack(fill="x", padx=16, pady=(0, 12))
        for c in range(self.MEMO_COLS):
            grid.columnconfigure(c, weight=1, uniform="memo")

        memos = self.settings.get("memos")
        if not isinstance(memos, list):
            memos = []

        for i in range(self.MEMO_COUNT):
            r, c = divmod(i, self.MEMO_COLS)
            cell = tk.Frame(grid, bg=self.CARD_BG, highlightbackground=LINE, highlightthickness=1)
            cell.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)
            text = tk.Text(cell, width=1, height=4, wrap="word", font=("Malgun Gothic", 9),
                            bd=0, relief="flat", bg=self.CARD_BG, fg=NUM, padx=6, pady=4,
                            highlightthickness=0, undo=True)
            text.pack(fill="both", expand=True)
            counter = tk.Label(cell, text="", bg=self.CARD_BG, fg="#a39c8c", font=("Consolas", 7))
            counter.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-2)
            if i < len(memos) and isinstance(memos[i], str):
                text.insert("1.0", memos[i][: self.MEMO_MAX])
            self.memo_boxes.append(text)

            text.bind("<KeyPress>", self._on_memo_key)
            text.bind("<KeyRelease>", lambda e, t=text, cl=counter: self._on_memo_edit(t, cl))
            text.bind("<<Paste>>", lambda e, t=text, cl=counter: t.after_idle(self._on_memo_edit, t, cl))
            text.bind("<Return>", lambda e: "break")
            text.bind("<Button-1>", lambda e, t=text, ce=cell, cl=counter: self._copy_memo(t, ce, cl))
            self._update_counter(text, counter)

    def _on_memo_key(self, event):
        text = event.widget
        if event.char and event.char >= " " and event.keysym not in ("Delete", "BackSpace"):
            has_selection = bool(text.tag_ranges("sel"))
            if not has_selection and len(text.get("1.0", "end-1c")) >= self.MEMO_MAX:
                return "break"
        return None

    def _on_memo_edit(self, text: tk.Text, counter: tk.Label):
        content = text.get("1.0", "end-1c")
        fixed = content.replace("\r", "").replace("\n", " ")[: self.MEMO_MAX]
        if fixed != content:
            pos = text.index("insert")
            text.delete("1.0", "end")
            text.insert("1.0", fixed)
            text.mark_set("insert", pos)
        self._update_counter(text, counter)
        self.settings["memos"] = [t.get("1.0", "end-1c") for t in self.memo_boxes]
        save_settings(self.settings)

    def _update_counter(self, text: tk.Text, counter: tk.Label):
        n = len(text.get("1.0", "end-1c"))
        counter.config(text=f"{n}/{self.MEMO_MAX}" if n else "")

    def _copy_memo(self, text: tk.Text, cell: tk.Frame, counter: tk.Label):
        content = text.get("1.0", "end-1c").strip()
        if not content:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        cell.config(highlightbackground=ACCENT)
        counter.config(text="복사됨", fg=ACCENT)

        def restore():
            cell.config(highlightbackground=LINE)
            counter.config(fg="#a39c8c")
            self._update_counter(text, counter)
        self.root.after(800, restore)

    # ---- 기본 계산기 (팝업) ----
    def _open_basic_calculator(self):
        if self._calc_win is not None and self._calc_win.winfo_exists():
            self._calc_win.deiconify()
            self._calc_win.lift()
            self._calc_win.focus_force()
            return
        win = tk.Toplevel(self.root)
        win.title("계산기")
        calc = BasicCalculator(win)
        fit_to_content(win, min_width=300)
        win.focus_force()
        calc.focus_input()
        self._calc_win = win

    def _copy_to_clipboard(self, var: tk.StringVar, button: tk.Button):
        value = var.get().strip()
        if not value:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        original = button.cget("text")
        button.config(text="복사됨")
        self.root.after(1000, lambda: button.config(text=original))

    # ---- 계산 ----
    def calculate(self):
        base_amount = to_num(self.base_amount_var.get())
        base_hour = to_num(self.base_hour_var.get())
        h_rate = round(base_amount / base_hour) if base_hour > 0 else 0
        self.h_rate_label.config(text=f"{fmt_won(h_rate)} / H")

        ref_amount = to_num(self.ref_amount_var.get())
        total_h = sum(to_num(var.get()) for _, var in self.time_rows)
        rate = to_num(self.rate_var.get())

        subtotal = round(ref_amount + total_h * h_rate)
        final = round(subtotal * (rate / 100))

        self.final_label.config(text=fmt_won(final))
        self.breakdown_labels["h_rate"].config(text=f"{fmt_won(h_rate)}/H")
        self.breakdown_labels["total_h"].config(text=f"{fmt_num(total_h, 2)}H")
        self.breakdown_labels["sum"].config(text=fmt_won(subtotal))
        self.breakdown_labels["rate"].config(text=f"{fmt_num(rate, 0)}%")

        if self._ready:
            self.settings["main"] = {
                "base_amount": self.base_amount_var.get(),
                "base_hour": self.base_hour_var.get(),
                "ref_amount": self.ref_amount_var.get(),
                "times": [v.get() for _, v in self.time_rows],
                "rate": self.rate_var.get(),
            }
            save_settings(self.settings)


def main():
    root = tk.Tk()
    LaborCalculatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
