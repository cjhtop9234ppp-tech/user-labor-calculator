"""사용자공임 산출 계산기(M/H적용) - Windows 데스크톱 버전.

index.html 과 동일한 계산 로직(반올림 시점 포함)을 tkinter GUI로 구현.
"""
from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation, localcontext
from tkinter import ttk

__version__ = "1.1.0"

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


VAT_RATE = 1.1  # 부가가치세 10% 기준


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
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"사용자공임 산출 계산기(M/H적용) v{__version__}")
        root.configure(bg=PAPER)

        self.time_rows: list[tuple[tk.Frame, tk.StringVar]] = []
        self._calc_win: tk.Toplevel | None = None

        self._build_style()
        self._build_header()
        self._build_step1()
        self._build_step2()
        self._build_result()

        self._add_time_row("1.55")
        self._add_time_row("0.5")

        self.calculate()
        self._fit_to_content()

    def _fit_to_content(self):
        fit_to_content(self.root, min_width=420)

    # ---- 스타일 ----
    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    def _card(self, step_label: str, title: str) -> tk.Frame:
        outer = tk.Frame(self.root, bg=PAPER)
        outer.pack(fill="x", padx=16, pady=(0, 8))

        badge = tk.Label(
            outer, text=step_label, bg=ACCENT, fg="white",
            font=("Consolas", 8, "bold"), padx=6, pady=1,
        )
        badge.pack(anchor="w")

        card = tk.Frame(outer, bg="#fffdf9", highlightbackground=LINE,
                         highlightthickness=1, bd=0)
        card.pack(fill="x")

        inner = tk.Frame(card, bg="#fffdf9", padx=12, pady=8)
        inner.pack(fill="x")

        tk.Label(inner, text=title, bg="#fffdf9", fg=ACCENT,
                  font=("Malgun Gothic", 10, "bold")).pack(anchor="w", pady=(0, 6))
        return inner

    def _labeled_entry(self, parent, label_text: str, var: tk.StringVar, unit: str):
        row = tk.Frame(parent, bg="#fffdf9")
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label_text, bg="#fffdf9", fg=MUTED,
                  font=("Malgun Gothic", 9), width=7, anchor="w").pack(side="left")
        entry = tk.Entry(row, textvariable=var, justify="right",
                          font=("Consolas", 10), fg=NUM,
                          relief="solid", bd=1, highlightthickness=0)
        entry.pack(side="left", fill="x", expand=True, ipady=2)
        entry.bind("<KeyRelease>", lambda e: self.calculate())
        tk.Label(row, text=unit, bg="#fffdf9", fg="#a39c8c",
                  font=("Malgun Gothic", 9), width=2).pack(side="left")
        return entry

    # ---- 헤더 ----
    def _build_header(self):
        head = tk.Frame(self.root, bg=PAPER)
        head.pack(fill="x", padx=16, pady=(14, 8))

        top_row = tk.Frame(head, bg=PAPER)
        top_row.pack(fill="x")

        title_box = tk.Frame(top_row, bg=PAPER)
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(title_box, text="사용자공임 산출 계산기", bg=PAPER, fg=INK,
                  font=("Georgia", 15, "bold")).pack(anchor="w")
        tk.Label(title_box, text="M/H(시간당 공임단가)를 적용해 사용자공임 최종 금액을 계산합니다",
                  bg=PAPER, fg=MUTED, font=("Malgun Gothic", 8)).pack(anchor="w", pady=(2, 0))

        btn_box = tk.Frame(top_row, bg=PAPER)
        btn_box.pack(side="right", anchor="n")
        for text, command in (("VAT 계산기", self._open_vat_calculator),
                              ("계산기", self._open_basic_calculator)):
            tk.Button(
                btn_box, text=text, command=command,
                bg="#fffdf9", fg=ACCENT, relief="solid", bd=1,
                font=("Malgun Gothic", 8, "bold"), highlightbackground=LINE,
                cursor="hand2",
            ).pack(side="left", padx=(4, 0), ipadx=4, ipady=2)

        tk.Frame(head, bg=LINE, height=1).pack(fill="x", pady=(8, 0))

    # ---- STEP 1 ----
    def _build_step1(self):
        inner = self._card("STEP 1", "M/H 계산 — 시간당 공임단가")

        self.base_amount_var = tk.StringVar(value="61,210")
        self.base_hour_var = tk.StringVar(value="1.580")
        self._labeled_entry(inner, "공임금액", self.base_amount_var, "원")
        self._labeled_entry(inner, "시간", self.base_hour_var, "H")

        result_row = tk.Frame(inner, bg=ACCENT_SOFT)
        result_row.pack(fill="x", pady=(6, 0))
        pad = tk.Frame(result_row, bg=ACCENT_SOFT)
        pad.pack(fill="x", padx=8, pady=5)
        tk.Label(pad, text="H단가 = 공임금액 ÷ 시간", bg=ACCENT_SOFT, fg=ACCENT,
                  font=("Consolas", 8)).pack(side="left")
        self.h_rate_label = tk.Label(pad, text="-", bg=ACCENT_SOFT, fg=ACCENT,
                                      font=("Consolas", 9, "bold"))
        self.h_rate_label.pack(side="right")

    # ---- STEP 2 ----
    def _build_step2(self):
        inner = self._card("STEP 2", "최종 결과값 계산")

        self.ref_amount_var = tk.StringVar(value="56,200")
        self._labeled_entry(inner, "기준금액", self.ref_amount_var, "원")

        tk.Label(inner, text="시간(H)", bg="#fffdf9", fg=MUTED,
                  font=("Malgun Gothic", 9)).pack(anchor="w", pady=(3, 3))
        self.time_list_frame = tk.Frame(inner, bg="#fffdf9")
        self.time_list_frame.pack(fill="x")

        add_btn = tk.Button(
            inner, text="+ 시간 추가", command=lambda: self._add_time_row("0"),
            bg="#fffdf9", fg=ACCENT, relief="solid", bd=1,
            font=("Malgun Gothic", 9), highlightbackground=LINE,
        )
        add_btn.pack(fill="x", pady=(3, 3), ipady=1)

        self.rate_var = tk.StringVar(value="65")
        self._labeled_entry(inner, "적용율", self.rate_var, "%")

    def _add_time_row(self, value: str):
        row = tk.Frame(self.time_list_frame, bg="#fffdf9")
        row.pack(fill="x", pady=2)

        var = tk.StringVar(value=value)
        entry = tk.Entry(row, textvariable=var, justify="right",
                          font=("Consolas", 10), fg=NUM,
                          relief="solid", bd=1)
        entry.pack(side="left", fill="x", expand=True, ipady=2)
        entry.bind("<KeyRelease>", lambda e: self.calculate())

        tk.Label(row, text="H", bg="#fffdf9", fg="#a39c8c",
                  font=("Malgun Gothic", 9)).pack(side="left", padx=(4, 2))

        remove_btn = tk.Button(
            row, text="×", command=lambda: self._remove_time_row(row, var),
            bg="#fffdf9", fg="#a39c8c", relief="flat", bd=0,
            font=("Malgun Gothic", 11), cursor="hand2",
        )
        remove_btn.pack(side="left")

        self.time_rows.append((row, var))
        self.calculate()
        self._fit_to_content()

    def _remove_time_row(self, row: tk.Frame, var: tk.StringVar):
        if len(self.time_rows) <= 1:
            return
        self.time_rows = [(r, v) for (r, v) in self.time_rows if r is not row]
        row.destroy()
        self.calculate()
        self._fit_to_content()

    # ---- 결과 카드 ----
    def _build_result(self):
        outer = tk.Frame(self.root, bg=PAPER)
        outer.pack(fill="x", padx=16, pady=(0, 14))

        card = tk.Frame(outer, bg=INK)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=INK, padx=16, pady=14)
        inner.pack(fill="x")

        tk.Label(inner, text="최종 결과값", bg=INK, fg="#a9c2b8",
                  font=("Malgun Gothic", 8)).pack()
        self.final_label = tk.Label(inner, text="0원", bg=INK, fg=PAPER,
                                     font=("Georgia", 24, "bold"))
        self.final_label.pack(pady=(3, 10))

        tk.Frame(inner, bg="#3a493f", height=1).pack(fill="x", pady=(0, 8))

        grid = tk.Frame(inner, bg=INK)
        grid.pack(fill="x")
        for i in range(2):
            grid.columnconfigure(i, weight=1)

        self.breakdown_labels = {}
        specs = [("h_rate", "H단가"), ("total_h", "총 H"),
                 ("sum", "공임합계"), ("rate", "적용율")]
        for idx, (key, label_text) in enumerate(specs):
            r, c = divmod(idx, 2)
            cell = tk.Frame(grid, bg=INK)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 12), pady=2)
            tk.Label(cell, text=label_text, bg=INK, fg="#7f9187",
                      font=("Malgun Gothic", 8)).pack(anchor="w")
            val = tk.Label(cell, text="-", bg=INK, fg="#c9d6cd",
                            font=("Consolas", 10, "bold"))
            val.pack(anchor="w")
            self.breakdown_labels[key] = val

    # ---- 기본 계산기 ----
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

    # ---- 이벤트 계산기: 공급가액/VAT 합산금액 ----
    def _open_vat_calculator(self):
        win = tk.Toplevel(self.root)
        win.title("공급가액 및 VAT 합산금액 산출")
        win.configure(bg=PAPER)
        win.resizable(False, False)

        tk.Label(win, text="공급가액 및 VAT 합산금액 산출", bg=PAPER, fg=INK,
                  font=("Georgia", 13, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(win, text="한쪽에 금액을 입력하면 반대쪽이 자동으로 계산됩니다 (부가세 10% 기준)",
                  bg=PAPER, fg=MUTED, font=("Malgun Gothic", 8)).pack(
            anchor="w", padx=16, pady=(0, 10))

        card = tk.Frame(win, bg="#fffdf9", highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", padx=16, pady=(0, 16))
        inner = tk.Frame(card, bg="#fffdf9", padx=14, pady=12)
        inner.pack(fill="x")

        supply_var = tk.StringVar()
        vat_total_var = tk.StringVar()
        updating = {"flag": False}

        def make_row(label_text: str, var: tk.StringVar) -> tk.Entry:
            row = tk.Frame(inner, bg="#fffdf9")
            row.pack(fill="x", pady=5)
            tk.Label(row, text=label_text, bg="#fffdf9", fg=MUTED,
                      font=("Malgun Gothic", 9), width=10, anchor="w").pack(side="left")
            entry = tk.Entry(row, textvariable=var, justify="right",
                              font=("Consolas", 11), fg=NUM,
                              relief="solid", bd=1)
            entry.pack(side="left", fill="x", expand=True, ipady=3)
            tk.Label(row, text="원", bg="#fffdf9", fg="#a39c8c",
                      font=("Malgun Gothic", 9), width=2).pack(side="left")
            copy_btn = tk.Button(
                row, text="복사", bg="#fffdf9", fg=ACCENT, relief="solid", bd=1,
                font=("Malgun Gothic", 8), cursor="hand2",
            )
            copy_btn.config(command=lambda: self._copy_to_clipboard(win, var, copy_btn))
            copy_btn.pack(side="left", padx=(6, 0))
            return entry

        supply_entry = make_row("공급가액", supply_var)
        make_row("VAT 합산금액", vat_total_var)

        def on_supply_change(*_args):
            if updating["flag"]:
                return
            updating["flag"] = True
            try:
                text = supply_var.get().strip()
                n = to_num(text)
                vat_total_var.set(f"{round(n * VAT_RATE):,}" if text else "")
            finally:
                updating["flag"] = False

        def on_vat_change(*_args):
            if updating["flag"]:
                return
            updating["flag"] = True
            try:
                text = vat_total_var.get().strip()
                n = to_num(text)
                supply_var.set(f"{round(n / VAT_RATE):,}" if text else "")
            finally:
                updating["flag"] = False

        supply_var.trace_add("write", on_supply_change)
        vat_total_var.trace_add("write", on_vat_change)

        fit_to_content(win, min_width=340)
        supply_entry.focus_set()

    def _copy_to_clipboard(self, win: tk.Toplevel, var: tk.StringVar, button: tk.Button):
        value = var.get().strip()
        if not value:
            return
        win.clipboard_clear()
        win.clipboard_append(value)
        original = button.cget("text")
        button.config(text="복사됨")
        win.after(1000, lambda: button.config(text=original))

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


def main():
    root = tk.Tk()
    LaborCalculatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
