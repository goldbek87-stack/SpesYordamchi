"""Spetsifikatsiya yordamchisi — Mexmash spetsifikatsiya PDF'ini o'qib,
1C'ga (Реализация товаров: Накладная) kiritish uchun ma'lumotlarni tayyorlaydi."""
import datetime
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from spec_parser import fmt, fmt_qty, parse_spec, plain

VERSION = "1.0"
COLUMN_SETS = {
    "Nomi | Miqdor | Narx | Summa": ("name", "qty", "price", "amount"),
    "Nomi | Miqdor | Summa": ("name", "qty", "amount"),
    "Nomi | Miqdor | Narx": ("name", "qty", "price"),
}


class App(tk.Tk):
    def __init__(self, path=None):
        super().__init__()
        self.title(f"Spetsifikatsiya yordamchisi {VERSION} — 1C Реализация uchun")
        self.geometry("1180x700")
        self.minsize(900, 520)
        self.spec = None
        self.status = tk.StringVar(value="PDF spetsifikatsiyani tanlang.")
        self._build()
        if path:
            self.load(path)

    # ---------- UI ----------
    def _build(self):
        st = ttk.Style(self)
        try:
            st.theme_use("vista")
        except tk.TclError:
            pass
        st.configure("Treeview", rowheight=24, font=("Segoe UI", 10))
        st.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        st.configure("Big.TLabel", font=("Segoe UI", 12, "bold"))

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="📂  PDF tanlash", command=self.choose).pack(side="left")
        self.file_lbl = ttk.Label(top, text="", foreground="#555")
        self.file_lbl.pack(side="left", padx=10)
        self.ontop = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Doim tepada", variable=self.ontop,
                        command=lambda: self.attributes("-topmost", self.ontop.get())).pack(side="right")

        # Sarlavha ma'lumotlari
        hdr = ttk.LabelFrame(self, text=" Накладная sarlavhasi ", padding=8)
        hdr.pack(fill="x", padx=8)
        self.fields = {}
        rows = [
            ("date", "Накладная sanasi (от):"),
            ("inn", "Kontragent INN:"),
            ("buyer", "Kontragent nomi:"),
            ("contract_no", "Shartnoma №:"),
            ("contract_date", "Shartnoma sanasi (от):"),
            ("spec_no", "Spetsifikatsiya №:"),
        ]
        for i, (key, label) in enumerate(rows):
            r, c = divmod(i, 2)
            ttk.Label(hdr, text=label).grid(row=r, column=c * 3, sticky="e", padx=(10, 4), pady=3)
            var = tk.StringVar()
            ent = ttk.Entry(hdr, textvariable=var, width=30, font=("Segoe UI", 11))
            ent.grid(row=r, column=c * 3 + 1, sticky="w", pady=3)
            ttk.Button(hdr, text="Nusxa", width=7,
                       command=lambda v=var, n=label: self.copy(v.get(), n)).grid(row=r, column=c * 3 + 2, padx=4)
            self.fields[key] = var
        self.fields["date"].set(datetime.date.today().strftime("%d.%m.%Y"))
        ttk.Label(hdr, text="Ombor: Шуруп склад", style="Big.TLabel").grid(row=3, column=0, columnspan=3,
                                                                       sticky="w", padx=10, pady=(6, 0))

        # Mahsulotlar jadvali
        mid = ttk.LabelFrame(self, text=" Товары  (qatorni 2 marta bosing — nomi nusxalanadi) ", padding=6)
        mid.pack(fill="both", expand=True, padx=8, pady=6)
        cols = ("no", "name", "key", "qty", "price", "amount", "total")
        heads = ("№", "Nomenklatura (spetsifikatsiyadagi)", "Qidiruv kaliti", "Количество",
                 "Цена (1C)", "Сумма (1C'ga shu)", "QQS bilan")
        widths = (40, 380, 150, 100, 100, 190, 140)
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c in ("name", "key") else "e", stretch=(c == "name"))
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.copy_cell("name"))
        self.tree.tag_configure("odd", background="#f4f7fb")

        rowbar = ttk.Frame(self, padding=(8, 0))
        rowbar.pack(fill="x")
        ttk.Label(rowbar, text="Tanlangan qator:").pack(side="left")
        for txt, fld in (("Nomi", "name"), ("Kalit", "key"), ("Miqdor", "qty"), ("Summa", "amount")):
            ttk.Button(rowbar, text=txt, command=lambda f=fld: self.copy_cell(f)).pack(side="left", padx=3)
        ttk.Button(rowbar, text="Keyingi qator ▶", command=self.next_row).pack(side="left", padx=12)

        ttk.Label(rowbar, text="Ustunlar:").pack(side="left", padx=(30, 4))
        self.colset = tk.StringVar(value=next(iter(COLUMN_SETS)))
        ttk.Combobox(rowbar, textvariable=self.colset, values=list(COLUMN_SETS), state="readonly",
                     width=26).pack(side="left")
        ttk.Button(rowbar, text="📋  Hammasini nusxalash",
                   command=self.copy_all).pack(side="left", padx=6)

        # Jami va tekshiruv
        bot = ttk.Frame(self, padding=8)
        bot.pack(fill="x")
        self.total_lbl = ttk.Label(bot, text="", style="Big.TLabel")
        self.total_lbl.pack(anchor="w")
        self.warn = tk.Text(bot, height=4, wrap="word", font=("Segoe UI", 10), relief="flat",
                            background=self.cget("background"))
        self.warn.pack(fill="x")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w",
                  padding=(6, 2)).pack(fill="x", side="bottom")

    # ---------- amallar ----------
    def choose(self):
        p = filedialog.askopenfilename(title="Spetsifikatsiya PDF", filetypes=[("PDF", "*.pdf"), ("Hammasi", "*.*")])
        if p:
            self.load(p)

    def load(self, path):
        try:
            s = parse_spec(path)
        except Exception as e:  # noqa
            messagebox.showerror("Xato", f"PDF o'qilmadi:\n{e}")
            return
        self.spec = s
        self.file_lbl.config(text=os.path.basename(path))
        self.fields["inn"].set(s.buyer_inn)
        self.fields["buyer"].set(s.buyer_name)
        self.fields["contract_no"].set(s.contract_no)
        self.fields["contract_date"].set(s.contract_date)
        self.fields["spec_no"].set(s.spec_no)
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(s.items):
            self.tree.insert("", "end", iid=str(i), tags=("odd",) if i % 2 else (),
                             values=(it.no, it.name, it.key, fmt_qty(it.qty), fmt(it.price_1c),
                                     fmt(it.amount), fmt(it.total)))
        if s.items:
            self.tree.selection_set("0")
            self.tree.focus("0")

        ok = s.jami_total is not None and s.sum_total == s.jami_total
        self.total_lbl.config(
            text=(f"Jami QQSsiz: {fmt(s.sum_amount)}    QQS: {fmt(s.sum_vat)}    "
                  f"QQS bilan: {fmt(s.sum_total)}     ←  1C'dagi «Всего» shu bo'lishi kerak"),
            foreground="#0a7d2c" if ok else "#c00000")
        self.warn.config(state="normal")
        self.warn.delete("1.0", "end")
        msgs = list(s.warnings)
        if ok and not msgs:
            msgs.append(f"✔ Spetsifikatsiya to'g'ri o'qildi: {len(s.items)} ta mahsulot, "
                        f"jami {fmt(s.jami_total)} spetsifikatsiya bilan mos.")
        msgs.append("Eslatma: 1C'da har qatorga Количество va СУММА ni yozing (narxni emas) — "
                    "1C narxni o'zi hisoblaydi va yaxlitlash farqi chiqmaydi.")
        self.warn.insert("1.0", "\n".join(msgs))
        self.warn.config(state="disabled")
        self.status.set(f"O'qildi: {os.path.basename(path)}")

    def copy(self, text, what="Matn"):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.status.set(f"Nusxalandi — {what.rstrip(':')}: {text}")

    def _item(self):
        sel = self.tree.selection()
        if not sel or not self.spec:
            return None
        return self.spec.items[int(sel[0])]

    def copy_cell(self, field):
        it = self._item()
        if not it:
            return
        val = {"name": it.name, "key": it.key, "qty": plain(it.qty, 3).rstrip("0").rstrip(","),
               "amount": plain(it.amount)}[field]
        self.copy(val, {"name": "Nomi", "key": "Kalit", "qty": "Miqdor", "amount": "Summa"}[field])

    def next_row(self):
        sel = self.tree.selection()
        if not sel:
            return
        n = int(sel[0]) + 1
        if n < len(self.spec.items):
            self.tree.selection_set(str(n))
            self.tree.focus(str(n))
            self.tree.see(str(n))

    def copy_all(self):
        if not self.spec or not self.spec.items:
            return
        fields = COLUMN_SETS[self.colset.get()]
        lines = []
        for it in self.spec.items:
            vals = {"name": it.name, "qty": plain(it.qty, 3).rstrip("0").rstrip(","),
                    "price": plain(it.price_1c), "amount": plain(it.amount)}
            lines.append("\t".join(vals[f] for f in fields))
        self.copy("\n".join(lines), f"{len(lines)} ta mahsulot")
        self.status.set(f"{len(lines)} ta mahsulot nusxalandi ({self.colset.get()}). "
                        f"1C'dagi Excel oynasiga Ctrl+V bilan qo'ying.")


if __name__ == "__main__":
    App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
