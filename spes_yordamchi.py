"""Spetsifikatsiya yordamchisi — Mexmash spetsifikatsiya PDF'ini o'qib,
1C'dagi «Реализация товаров: Накладная» ga o'zi yozadi."""
import datetime
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from spec_parser import fmt, fmt_qty, parse_spec, plain

VERSION = "2.2"


class App(tk.Tk):
    def __init__(self, path=None):
        super().__init__()
        self.title(f"Spetsifikatsiya yordamchisi {VERSION} — 1C Реализация uchun")
        self.geometry("1180x720")
        self.minsize(900, 560)
        self.spec = None
        self.status = tk.StringVar(value="PDF spetsifikatsiyani tanlang.")
        self.asks = queue.Queue()
        try:
            import avto1c
            self.avto = avto1c
            self.cfg = avto1c.load_config()
        except Exception as e:  # noqa — masalan Linux'da sinov paytida
            self.avto, self.cfg = None, {"sklad_nomi": "Шуруп склад", "qadamma_qadam": True, "points": {}}
            print("avto1c yuklanmadi:", e)
        self._build()
        self.after(150, self._poll_asks)
        if path:
            self.load(path)

    # ================= UI =================
    def _build(self):
        st = ttk.Style(self)
        try:
            st.theme_use("vista")
        except tk.TclError:
            pass
        st.configure("Treeview", rowheight=24, font=("Segoe UI", 10))
        st.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        st.configure("Big.TLabel", font=("Segoe UI", 12, "bold"))
        st.configure("Go.TButton", font=("Segoe UI", 12, "bold"), padding=(14, 6))

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="📂  PDF tanlash", command=self.choose).pack(side="left")
        self.file_lbl = ttk.Label(top, text="", foreground="#555")
        self.file_lbl.pack(side="left", padx=10)
        ttk.Button(top, text="▶  1C'GA YOZISH", style="Go.TButton", command=self.start_run).pack(side="right")
        ttk.Button(top, text="🎓  O'rgatish", command=self.start_calib).pack(side="right", padx=8)
        self.step_var = tk.BooleanVar(value=self.cfg.get("qadamma_qadam", True))
        ttk.Checkbutton(top, text="Har mahsulotdan keyin so'rasin", variable=self.step_var).pack(side="right", padx=8)
        self.calib_lbl = ttk.Label(top, text="")
        self.calib_lbl.pack(side="right", padx=8)
        self._update_calib_lbl()

        hdr = ttk.LabelFrame(self, text=" Накладная sarlavhasi ", padding=8)
        hdr.pack(fill="x", padx=8)
        self.fields = {}
        rows = [
            ("date", "Накладная sanasi (от):"),
            ("inn", "Kontragent INN:"),
            ("buyer", "Kontragent nomi:"),
            ("contract_no", "Shartnoma №:"),
            ("contract_date", "Shartnoma sanasi (от):"),
            ("sklad", "Склад:"),
        ]
        for i, (key, label) in enumerate(rows):
            r, c = divmod(i, 2)
            ttk.Label(hdr, text=label).grid(row=r, column=c * 3, sticky="e", padx=(10, 4), pady=3)
            var = tk.StringVar()
            ttk.Entry(hdr, textvariable=var, width=30, font=("Segoe UI", 11)).grid(row=r, column=c * 3 + 1,
                                                                                 sticky="w", pady=3)
            ttk.Button(hdr, text="Nusxa", width=7,
                       command=lambda v=var, n=label: self.copy(v.get(), n)).grid(row=r, column=c * 3 + 2, padx=4)
            self.fields[key] = var
        self.fields["date"].set(datetime.date.today().strftime("%d.%m.%Y"))
        self.fields["sklad"].set(self.cfg.get("sklad_nomi", "Шуруп склад"))

        mid = ttk.LabelFrame(self, text=" Товары  («Подбор'da qidiruv» ustunini 2 marta bosib o'zgartirsa bo'ladi) ",
                             padding=6)
        mid.pack(fill="both", expand=True, padx=8, pady=6)
        cols = ("no", "name", "search", "qty", "price", "amount", "total")
        heads = ("№", "Nomenklatura (spetsifikatsiyadagi)", "Подбор'da qidiruv", "Количество",
                 "Цена (1C)", "Сумма (1C'ga shu)", "QQS bilan")
        widths = (40, 360, 170, 100, 100, 160, 140)
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c in ("name", "search") else "e", stretch=(c == "name"))
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.tag_configure("odd", background="#f4f7fb")

        rowbar = ttk.Frame(self, padding=(8, 0))
        rowbar.pack(fill="x")
        ttk.Label(rowbar, text="Qo'lda nusxalash — tanlangan qator:").pack(side="left")
        for txt, fld in (("Nomi", "name"), ("Qidiruv", "search"), ("Miqdor", "qty"), ("Summa", "amount")):
            ttk.Button(rowbar, text=txt, command=lambda f=fld: self.copy_cell(f)).pack(side="left", padx=3)
        ttk.Button(rowbar, text="Keyingi qator ▶", command=self.next_row).pack(side="left", padx=12)

        bot = ttk.Frame(self, padding=8)
        bot.pack(fill="x")
        self.total_lbl = ttk.Label(bot, text="", style="Big.TLabel")
        self.total_lbl.pack(anchor="w")
        self.warn = tk.Text(bot, height=4, wrap="word", font=("Segoe UI", 10), relief="flat",
                            background=self.cget("background"))
        self.warn.pack(fill="x")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w",
                  padding=(6, 2)).pack(fill="x", side="bottom")

    def _update_calib_lbl(self):
        ok = self.avto and self.avto.is_calibrated(self.cfg)
        self.calib_lbl.config(text="✔ o'rgatilgan" if ok else "⚠ avval «O'rgatish» qiling",
                              foreground="#0a7d2c" if ok else "#c00000")

    # ================= PDF =================
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
        self.fields["contract_no"].set(s.contract_no.replace("-", "/")
                                       if self.cfg.get("shartnoma_chiziq_slash", True) else s.contract_no)
        self.fields["contract_date"].set(s.contract_date)
        self.refresh_rows()
        ok = s.jami_total is not None and s.sum_total == s.jami_total
        self.total_lbl.config(
            text=(f"Jami QQSsiz: {fmt(s.sum_amount)}    QQS: {fmt(s.sum_vat)}    "
                  f"QQS bilan: {fmt(s.sum_total)}     ←  1C'dagi «Всего» shu bo'lishi kerak"),
            foreground="#0a7d2c" if ok else "#c00000")
        msgs = list(s.warnings)
        if ok and not msgs:
            msgs.append(f"✔ Spetsifikatsiya to'g'ri o'qildi: {len(s.items)} ta mahsulot, spetsifikatsiya №{s.spec_no}, "
                        f"jami {fmt(s.jami_total)} mos.")
        msgs.append("Endi 1C'da yangi «Реализация товаров: Накладная» oynasini oching va «▶ 1C'GA YOZISH» ni bosing.")
        self.warn.config(state="normal")
        self.warn.delete("1.0", "end")
        self.warn.insert("1.0", "\n".join(msgs))
        self.warn.config(state="disabled")
        self.status.set(f"O'qildi: {os.path.basename(path)}")

    def refresh_rows(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.spec.items):
            self.tree.insert("", "end", iid=str(i), tags=("odd",) if i % 2 else (),
                             values=(it.no, it.name, it.search, fmt_qty(it.qty), fmt(it.price_1c),
                                     fmt(it.amount), fmt(it.total)))
        if self.spec.items:
            iid = sel[0] if sel else "0"
            self.tree.selection_set(iid)
            self.tree.focus(iid)

    def on_double(self, event):
        it = self._item()
        if not it:
            return
        if self.tree.identify_column(event.x) == "#3":
            new = simpledialog.askstring("Подбор'da qidiruv",
                                         f"{it.name}\n\n1C Подбор oynasida nima deb qidirilsin?",
                                         initialvalue=it.search, parent=self)
            if new and new.strip():
                it.search = new.strip()
                self.refresh_rows()
        else:
            self.copy_cell("name")

    # ================= nusxalash =================
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
        if it:
            val = {"name": it.name, "search": it.search, "qty": it.qty_text, "amount": it.amount_text}[field]
            self.copy(val, field)

    def next_row(self):
        sel = self.tree.selection()
        if sel and int(sel[0]) + 1 < len(self.spec.items):
            n = str(int(sel[0]) + 1)
            self.tree.selection_set(n)
            self.tree.focus(n)
            self.tree.see(n)

    # ================= kichik oyna (o'rgatish/ish paytida) =================
    def _mini(self, title):
        w = tk.Toplevel(self)
        w.title(title)
        w.attributes("-topmost", True)
        sh = self.winfo_screenheight()
        w.geometry(f"360x230+8+{sh - 320}")    # pastki chap burchak (1C bo'limlar menyusi ustida)
        lbl = ttk.Label(w, text="", wraplength=340, font=("Segoe UI", 10), justify="left")
        lbl.pack(fill="both", expand=True, padx=10, pady=8)
        btns = ttk.Frame(w)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        return w, lbl, btns

    def _rect(self, w):
        return (w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(),
                w.winfo_rooty() + w.winfo_height())

    # ================= O'RGATISH =================
    def start_calib(self):
        if not self.avto:
            messagebox.showerror("Xato", "Avtomatik yozish moduli yuklanmadi.")
            return
        if not messagebox.askokcancel(
                "O'rgatish",
                "1C'da yangi «Реализация товаров: Накладная» oynasini oching va 1C oynasini "
                "TO'LIQ EKRAN (maximize) holatida qoldiring.\n\n"
                "Dastur ketma-ket so'raydi — 1C'dagi o'sha joyni sichqoncha bilan bir marta bosasiz, "
                "keyin kichik oynadagi «Keyingi ▶» ni bosasiz.\n\nTayyormisiz?"):
            return
        self.iconify()
        w, lbl, btns = self._mini("O'rgatish")
        w.geometry(f"400x260+8+{self.winfo_screenheight() - 350}")
        points = {}
        steps = list(self.avto.POINTS)
        st = {"i": 0, "lst": None, "got": None}

        def stop_listener():
            if st["lst"]:
                try:
                    st["lst"].stop()
                except Exception:  # noqa
                    pass
                st["lst"] = None

        def clear_btns():
            for c in btns.winfo_children():
                c.destroy()

        def cancel():
            stop_listener()
            w.destroy()
            self.deiconify()

        def finish():
            stop_listener()
            self.cfg["points"] = points
            self.avto.save_config(self.cfg)
            w.destroy()
            self.deiconify()
            self._update_calib_lbl()
            messagebox.showinfo("O'rgatish", "Tayyor! Joylar eslab qolindi.\n\n"
                                             "Endi 1C'dagi bu накладная'ni yopib (saqlamasdan), "
                                             "yangisini ochib «1C'GA YOZISH» ni sinab ko'ring.")

        def arm():
            """Joriy qadam uchun bosishni kutish."""
            key, text = steps[st["i"]]
            st["got"] = None
            lbl.config(text=f"Qadam {st['i'] + 1}/{len(steps)}\n\n{text}\n\n⏳ 1C'da bosishingizni kutyapman…")
            clear_btns()
            ttk.Button(btns, text="Bekor qilish", command=cancel).pack(side="right")

            def on_point(x, y):          # pynput oqimidan — faqat qiymatni saqlaymiz
                st["got"] = (x, y)

            def start_listen():
                st["lst"] = self.avto.capture_click(on_point, ignore_rect=lambda: rect)
            rect = self._rect(w)
            self.after(600, start_listen)    # avvalgi bosishlar hisobga olinmasin
            self.after(700, poll)

        def poll():
            if not w.winfo_exists():
                return
            if st["got"] is None:
                self.after(100, poll)
                return
            stop_listener()
            key, text = steps[st["i"]]
            points[key] = list(st["got"])
            lbl.config(text=f"Qadam {st['i'] + 1}/{len(steps)}\n\n{text}\n\n"
                            f"✔ Eslab qolindi: {st['got'][0]}, {st['got'][1]}\n\n"
                            "To'g'ri joyni bosgan bo'lsangiz — «Keyingi ▶».\nNoto'g'ri bo'lsa — «Qaytadan».")
            clear_btns()
            last = st["i"] == len(steps) - 1
            ttk.Button(btns, text="Tugatish ✔" if last else "Keyingi ▶",
                       command=lambda: (finish() if last else next_step())).pack(side="left")
            ttk.Button(btns, text="Qaytadan", command=arm).pack(side="left", padx=8)
            ttk.Button(btns, text="Bekor qilish", command=cancel).pack(side="right")
            w.lift()

        def next_step():
            st["i"] += 1
            arm()

        arm()

    # ================= 1C'GA YOZISH =================
    def start_run(self):
        if not self.spec or not self.spec.items:
            messagebox.showwarning("PDF", "Avval spetsifikatsiya PDF'ini tanlang.")
            return
        if not self.avto or not self.avto.is_calibrated(self.cfg):
            messagebox.showwarning("O'rgatish", "Avval «🎓 O'rgatish» ni bir marta qiling.")
            return
        self.spec.buyer_inn = self.fields["inn"].get().strip()
        self.spec.contract_no = self.fields["contract_no"].get().strip()
        if not self.spec.buyer_inn:
            messagebox.showwarning("INN", "Kontragent INN o'qilmadi — maydonga qo'lda yozing.")
            return
        self.cfg["sklad_nomi"] = self.fields["sklad"].get().strip() or "Шуруп склад"
        self.cfg["qadamma_qadam"] = self.step_var.get()
        self.avto.save_config(self.cfg)
        if not messagebox.askokcancel(
                "1C'ga yozish",
                "1C'da YANGI «Реализация товаров: Накладная» oynasi ochiq va to'liq ekran holatida bo'lsin.\n\n"
                "«OK» bosgandan keyin 3 soniyada boshlanadi. Ish paytida sichqoncha va klaviaturaga tegmang.\n\n"
                "To'xtatish: Esc tugmasi (yoki sichqonchani ekranning yuqori chap burchagiga olib boring)."):
            return
        self.iconify()
        w, lbl, btns = self._mini("1C'ga yozilyapti")
        self._run_win = (w, lbl, btns)
        runner = self.avto.Runner(self.cfg, self._ask_from_thread,
                                  lambda t: self.after(0, lbl.config, {"text": t + "\n\n(To'xtatish: Esc)"}))
        date_text = self.fields["date"].get().strip()

        def work():
            try:
                runner.run(self.spec, date_text, self.spec.items)
                self.after(0, self._run_done, True, "")
            except self.avto.Stopped:
                self.after(0, self._run_done, False, "To'xtatildi.")
            except Exception as e:  # noqa
                self.after(0, self._run_done, False, f"Xato: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _ask_from_thread(self, text):
        ev = threading.Event()
        box = {}
        self.asks.put((text, ev, box))
        ev.wait()
        return box.get("ok", False)

    def _poll_asks(self):
        try:
            while True:
                text, ev, box = self.asks.get_nowait()
                self._show_ask(text, ev, box)
        except queue.Empty:
            pass
        self.after(150, self._poll_asks)

    def _show_ask(self, text, ev, box):
        w, lbl, btns = self._run_win
        lbl.config(text=text)
        w.geometry(f"420x300+8+{self.winfo_screenheight() - 390}")
        for c in btns.winfo_children():
            c.destroy()

        def answer(ok):
            box["ok"] = ok
            for c in btns.winfo_children():
                c.destroy()
            lbl.config(text="Davom etyapti…")
            w.geometry(f"360x230+8+{self.winfo_screenheight() - 320}")
            self.after(400, ev.set)     # oyna yopilib, 1C'ga fokus qaytishi uchun

        ttk.Button(btns, text="Davom ▶", command=lambda: answer(True)).pack(side="left")
        ttk.Button(btns, text="To'xtatish", command=lambda: answer(False)).pack(side="right")
        w.lift()

    def _run_done(self, ok, msg):
        w = self._run_win[0]
        w.destroy()
        self.deiconify()
        if ok:
            messagebox.showinfo(
                "Tayyor",
                f"Mahsulotlar hujjatga o'tkazildi.\n\n1C'dagi «Всего» shu bo'lishi kerak:\n"
                f"{fmt(self.spec.sum_total)} so'm\n\nQolgani o'zingizda:\n"
                "1) «Документ подписан» belgisini qo'ying\n2) «Выписать счет-фактуру»\n"
                "3) «Провести» → yashil belgi → «Провести и закрыть»")
        else:
            messagebox.showwarning("To'xtadi", msg + "\n\n1C'dagi hujjatni tekshiring.")


if __name__ == "__main__":
    App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
