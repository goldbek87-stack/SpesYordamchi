"""1C oynasini klaviatura va sichqoncha orqali to'ldirish (odam qanday qilsa, shunday)."""
import json
import os
import threading
import time

import pyautogui
import pyperclip
from pynput import keyboard, mouse

pyautogui.FAILSAFE = True      # sichqonchani ekran burchagiga olib borsa — to'xtaydi
pyautogui.PAUSE = 0.05

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SpesYordamchi")
CONFIG_FILE = os.path.join(CONFIG_DIR, "sozlama.json")

# O'rgatish qadamlari: (kalit, ko'rsatma)
POINTS = [
    ("date", "Накладная № yonidagi «от:» SANA maydonini bosing."),
    ("kontragent", "«Контрагент» maydonini bosing."),
    ("dogovor", "«Договор» maydonini bosing."),
    ("sklad", "«Склад» maydonini bosing."),
    ("podbor", "Товары ostidagi «Подбор» tugmasini bosing (Подбор oynasi ochiladi)."),
    ("qidiruv", "Подбор oynasida O'NG tomondagi qidiruv maydonini bosing (mahsulotlar ro'yxati tepasida, "
                "lupa 🔍 belgisi yonidagi oq maydon)."),
    ("first_row", "Подбор oynasida mahsulotlar ro'yxatining BIRINCHI qatoridagi NOMNI bosing "
                  "(«Наименование» ustunida)."),
    ("perenesti", "Подбор oynasidagi «Перенести в документ» tugmasini bosing."),
]

DEFAULT = {
    "points": {},
    "sklad_nomi": "Шуруп склад",
    "tezlik": 1.0,                 # 1 = oddiy; 2 = 2 barobar sekin (kompyuter sekin bo'lsa)
    # Miqdor oynasida bosiladigan tugmalar ketma-ketligi:
    # QTY = miqdor, SUM = summa, TAB, ENTER, CTRL+ENTER
    "miqdor_oynasi": ["QTY", "TAB", "TAB", "SUM", "TAB", "ENTER"],
    "qadamma_qadam": True,         # har mahsulotdan keyin to'xtab so'rash (birinchi sinovlar uchun)
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT))
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def is_calibrated(cfg):
    return all(k in cfg["points"] for k, _ in POINTS)


class Stopped(Exception):
    pass


class Runner:
    """1C'ni to'ldiruvchi. ui_ask(matn) -> True/False (davom/to'xtat) asosiy oynada so'raydi."""

    def __init__(self, cfg, ui_ask, ui_status):
        self.cfg = cfg
        self.ask = ui_ask
        self.status = ui_status
        self.stop = threading.Event()
        self._kl = keyboard.Listener(on_press=self._on_key)

    def _on_key(self, key):
        if key == keyboard.Key.esc:
            self.stop.set()

    # --- yordamchi amallar ---
    def wait(self, sec):
        end = time.time() + sec * float(self.cfg.get("tezlik", 1.0))
        while time.time() < end:
            if self.stop.is_set():
                raise Stopped()
            time.sleep(0.05)

    def click(self, name):
        x, y = self.cfg["points"][name]
        pyautogui.click(x, y)
        self.wait(0.4)

    def paste(self, text):
        pyperclip.copy(str(text))
        self.wait(0.1)
        pyautogui.hotkey("ctrl", "v")
        self.wait(0.3)

    def key(self, *keys):
        if self.stop.is_set():
            raise Stopped()
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        self.wait(0.25)

    def fill_field(self, name, text, settle=1.5):
        """Maydonni bosib, tozalab (Shift+F4), matnni qo'yib, Tab bilan tasdiqlash."""
        self.click(name)
        self.key("shift", "f4")
        self.paste(text)
        self.wait(settle)          # 1C qidirib ulgursin
        self.key("tab")
        self.wait(0.8)

    def read_cell(self):
        """Tanlangan qator nomini Ctrl+C orqali o'qish. O'qib bo'lmasa — None."""
        sentinel = "~~spes~~"
        pyperclip.copy(sentinel)
        self.wait(0.1)
        pyautogui.hotkey("ctrl", "c")
        self.wait(0.5)
        try:
            txt = pyperclip.paste()
        except Exception:  # noqa
            return None
        if txt == sentinel:
            return None
        return " ".join(txt.split())

    def manual(self, i, n, it, why):
        pyperclip.copy(it.amount_text)
        self.checkpoint(
            f"{i}/{n}: «{it.name}» avtomatik topilmadi.\n{why}\n\n"
            f"Shu mahsulotni 1C Подбор'da O'ZINGIZ tanlang va kiriting:\n"
            f"   Количество: {it.qty_text}\n   Сумма: {it.amount_text}  (nusxalandi — Ctrl+V)\n\n"
            "Keyin «Davom» bosing — dastur keyingi mahsulotga o'tadi.")

    def checkpoint(self, text):
        if not self.ask(text):
            raise Stopped()

    # --- asosiy ish ---
    def run(self, spec, date_text, items):
        self._kl.start()
        try:
            self.status("3 soniyadan keyin boshlanadi… (to'xtatish: Esc)")
            self.wait(3)

            self.status("Sana…")
            self.fill_field("date", date_text, settle=0.3)
            self.status("Kontragent (INN bo'yicha)…")
            self.fill_field("kontragent", spec.buyer_inn, settle=2.5)
            self.status("Shartnoma…")
            self.fill_field("dogovor", spec.contract_no, settle=2.0)
            self.status("Склад…")
            self.fill_field("sklad", self.cfg["sklad_nomi"], settle=1.5)

            self.checkpoint(
                "1C'dagi sarlavhani tekshiring:\n\n"
                f"• Kontragent: {spec.buyer_name} (INN {spec.buyer_inn})\n"
                f"• Shartnoma: {spec.contract_no} dan {spec.contract_date}\n"
                f"• Склад: {self.cfg['sklad_nomi']}\n\n"
                "Noto'g'ri bo'lsa — hozir 1C'da qo'lda tuzating (kontragent bo'lmasa yarating), "
                "keyin «Davom» bosing.\nDavom etsa mahsulotlar kiritiladi.")

            self.status("Подбор ochilyapti…")
            self.click("podbor")
            self.wait(3)

            n = len(items)
            for i, it in enumerate(items, 1):
                self.status(f"Mahsulot {i}/{n}: {it.name}")
                # 1) qidiruv maydoniga qidiriladigan matnni yozish
                self.click("qidiruv")
                self.key("ctrl", "a")
                self.paste(it.search)
                self.key("enter")
                self.wait(2.0)
                # 2) birinchi topilgan qatorni tanlash va nomini tekshirish
                self.click("first_row")
                found = self.read_cell()
                if found is not None and not same_product(it.search, found):
                    self.manual(i, n, it, f"1C'da birinchi chiqqan: «{found or '(hech narsa topilmadi)'}»")
                    continue
                # 3) miqdor oynasi
                self.key("enter")
                self.wait(1.2)
                for step in self.cfg["miqdor_oynasi"]:
                    if step == "QTY":
                        self.paste(it.qty_text)
                    elif step == "SUM":
                        self.paste(it.amount_text)
                    elif step == "CTRL+ENTER":
                        self.key("ctrl", "enter")
                    else:
                        self.key(step.lower())
                self.wait(0.8)
                if self.cfg.get("qadamma_qadam") and i < n:
                    self.checkpoint(
                        f"{i}/{n}: «{it.name}»\n{it.qty_text} kg, summa {it.amount_text}\n\n"
                        "Pastdagi «Подобранные позиции» ro'yxatiga to'g'ri tushdimi?\n"
                        "To'g'ri bo'lsa «Davom». Xato bo'lsa — 1C'da tuzatib, keyin «Davom».")

            self.status("Hujjatga o'tkazilyapti…")
            self.click("perenesti")
            self.wait(2)
            return True
        except pyautogui.FailSafeException:
            raise Stopped()
        finally:
            self._kl.stop()


def _norm(t):
    t = (t or "").lower().replace("x", "х").replace("×", "х").replace(".", ",").replace("ё", "е")
    return "".join(t.split())


def same_product(search, found):
    """1C'dagi nom qidirilgan matnni o'z ichiga oladimi (bo'shliq/harf farqlarisiz)."""
    return bool(found) and _norm(search) in _norm(found)


def capture_click(on_point, ignore_rect=None):
    """Keyingi chap tugma bosilishini ushlaydi; on_point(x, y) chaqiriladi."""
    def on_click(x, y, button, pressed):
        if not pressed or button != mouse.Button.left:
            return True
        if ignore_rect:
            l, t, r, b = ignore_rect()
            if l <= x <= r and t <= y <= b:
                return True
        on_point(int(x), int(y))
        return False
    lst = mouse.Listener(on_click=on_click)
    lst.start()
    return lst
