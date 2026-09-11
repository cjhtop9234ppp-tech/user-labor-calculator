"""사용자공임 산출 계산기(M/H적용) - Windows 데스크톱 버전.

index.html 과 동일한 계산 로직(반올림 시점 포함)을 tkinter GUI로 구현.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

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


class LaborCalculatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("사용자공임 산출 계산기(M/H적용)")
        root.configure(bg=PAPER)

        self.time_rows: list[tuple[tk.Frame, tk.StringVar]] = []

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
        # 실제 렌더링된 위젯 크기에 맞춰 창 크기를 자동 산정한다.
        # DPI/폰트에 따라 요구 높이가 달라지므로 고정 geometry를 쓰면 내용이 잘릴 수 있다.
        self.root.update_idletasks()
        width = max(self.root.winfo_reqwidth(), 420)
        height = self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)

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
        tk.Label(head, text="사용자공임 산출 계산기", bg=PAPER, fg=INK,
                  font=("Georgia", 15, "bold")).pack(anchor="w")
        tk.Label(head, text="M/H(시간당 공임단가)를 적용해 사용자공임 최종 금액을 계산합니다",
                  bg=PAPER, fg=MUTED, font=("Malgun Gothic", 8)).pack(anchor="w", pady=(2, 8))
        tk.Frame(head, bg=LINE, height=1).pack(fill="x")

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
