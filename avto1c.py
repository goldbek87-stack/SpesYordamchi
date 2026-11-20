"""1C oynasini klaviatura va sichqoncha orqali to'ldirish (odam qanday qilsa, shunday).

Har bir qadamdan keyin ekran o'zgarishini kutadi va iloji bo'lsa yozilgan qiymatni
Ctrl+C orqali qayta o'qib tekshiradi. Tekshiruvdan o'tmasa — to'xtaydi va sababini aytadi.
"""
import base64
import ctypes
import json
import os
import threading
import time

import pyautogui
import pyperclip
from pynput import keyboard, mouse

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SpesYordamchi")
CONFIG_FILE = os.path.join(CONFIG_DIR, "sozlama.json")

# O'rgatish qadamlari: (kalit, ko'rsatma, tur)   tur: "click" — bosishni ushlash, "info" — faqat ko'rsatma
POINTS = [
    ("prodaja", "1C chap menyusidagi «Продажи» bo'limini bosing.", "click"),
    ("real_link", "Ochilgan ro'yxatdagi «Реализация (акты, накладные)» ni bosing.", "click"),
    ("real_btn", "Ro'yxat oynasidagi yashil «⊕ Реализация ▾» tugmasini bosing.\n"
                 "Menyu ochiladi — KEYINGI'ni bosmang, darhol menyudagi «Товары (накладная)» ni bosing.", "click"),
    ("tovary_nakl", "Ochilgan menyudagi «Товары (накладная)» ni bosing (yangi накладная ochiladi).\n"
                    "Menyu yopilib qolgan bo'lsa — «Qaytadan» ni bosing.", "click"),
    ("date", "Yangi накладная'da «Накладная №» yonidagi «от:» SANA maydonini bosing.", "click"),
    ("kontragent", "«Контрагент» maydonini bosing, keyin istalgan kontragentni TANLANG (Подбор ishlashi uchun kerak).", "click"),
    ("dogovor", "«Договор» maydonini bosing, keyin shartnomani TANLANG.", "click"),
    ("sklad", "«Склад» maydonini bosing, keyin «Шуруп склад» ni TANLANG.", "click"),
    ("podbor", "Товары ostidagi «Подбор» tugmasini bosing (Подбор oynasi ochiladi).", "click"),
    ("qidiruv", "Подбор oynasida O'NG tomondagi qidiruv maydonini bosing (ro'yxat tepasida, lupa 🔍 yonida).", "click"),
    ("first_row", "Mahsulotlar ro'yxatining BIRINCHI qatoridagi NOMNI bir marta bosing.", "click"),
    ("_open_dlg", "Endi o'sha mahsulotni IKKI MARTA bosing — Количество/Цена/Сумма oynasi ochilsin.\n"
                  "Oyna ochilgach «Keyingi ▶» ni bosing.", "info"),
    ("dlg_qty", "Oynadagi «Количество» maydonini bosing va 1 deb yozing.", "click"),
    ("dlg_price", "Oynadagi «Цена» maydonini bosing, 1 deb yozing va Tab bosing — Сумма chiqadi.", "click"),
    ("dlg_sum", "Oynadagi «Сумма» maydonini bosing.", "click"),
    ("dlg_ok", "Oynadagi «OK» tugmasini bosing.", "click"),
    ("perenesti", "Подбор oynasidagi «Перенести в документ» tugmasini bosing.", "click"),
]
CLICK_KEYS = [k for k, _, t in POINTS if t == "click"]

DEFAULT = {
    "points": {},
    "sklad_nomi": "Шуруп склад",
    "tezlik": 1.0,                 # 1 = oddiy; 2 = 2 barobar sekin
    "qadamma_qadam": True,
    "shartnoma_chiziq_slash": True,
    "anchors": {},
    "cfg_versiya": 5,
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT))
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("cfg_versiya", 0) < DEFAULT["cfg_versiya"]:
            saved = {k: v for k, v in saved.items() if k in ("sklad_nomi", "tezlik", "qadamma_qadam")}
        cfg.update(saved)
        cfg["cfg_versiya"] = DEFAULT["cfg_versiya"]
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# Belgi (anchor): o'rgatishda olingan kichik rasm — ish paytida "to'g'ri oyna ochiqmi?" deb tekshiriladi.
#   doc    — накладная oynasi: «Подбор» tugmasi atrofi
#   podbor — Подбор oynasi: «Перенести в документ» tugmasi atrofi
#   dlg    — Количество/Цена/Сумма oynasi: «OK» tugmasi atrofi
ANCHORS = {"doc": "podbor", "podbor": "perenesti", "dlg": "dlg_ok"}
PATCH_W, PATCH_H = 80, 28


def grab_patch(img, x, y):
    box = (x - PATCH_W // 2, y - PATCH_H // 2, x + PATCH_W // 2, y + PATCH_H // 2)
    return img.convert("L").crop(box)


def patch_to_cfg(patch):
    return base64.b64encode(patch.tobytes()).decode("ascii")


def patch_from_cfg(data):
    from PIL import Image
    return Image.frombytes("L", (PATCH_W, PATCH_H), base64.b64decode(data))


def patch_diff(a, b):
    from PIL import ImageChops, ImageStat
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def is_calibrated(cfg):
    return all(k in cfg["points"] for k in CLICK_KEYS) and all(k in cfg.get("anchors", {}) for k in ANCHORS)


def _norm(t):
    t = (t or "").lower().replace("x", "х").replace("×", "х").replace(".", ",").replace("ё", "е")
    return "".join(t.split())


def same_product(search, found):
    return bool(found) and _norm(search) in _norm(found)


def num_equal(text, expected):
    """'6 540 267,86' == '6540267,86' ?"""
    a = "".join(ch for ch in (text or "") if ch.isdigit() or ch in ",.").replace(".", ",")
    b = expected.replace(".", ",")
    try:
        return abs(float(a.replace(",", ".")) - float(b.replace(",", "."))) < 0.005
    except ValueError:
        return False


# ---------- 1C oynasini topish va oldinga chiqarish (Windows) ----------
def window_titles():
    """Ko'rinib turgan barcha oynalar: [(hwnd, nom)]."""
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except (AttributeError, OSError):
        return []
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    out = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        try:
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    out.append((hwnd, buf.value))
        except Exception:  # noqa
            pass
        return True
    cb_ptr = proto(cb)
    user32.EnumWindows(ctypes.cast(cb_ptr, ctypes.c_void_p), 0)
    return out


def activate_1c(log=print):
    """1C oynasini topib oldinga chiqaradi va to'liq ekran qiladi.
    Topilmasa ham False qaytaradi, lekin ish davom etadi (birinchi bosish 1C'ni oldinga chiqaradi)."""
    titles = window_titles()
    if not titles:
        return False
    keys = ("1С:Предприятие", "1C:Предприятие", "Предприятие", "MEXMASH")
    h = next((hw for hw, t in titles if any(k.lower() in t.lower() for k in keys)
              and "Spetsifikatsiya" not in t), None)
    if not h:
        log("   1C oynasi topilmadi. Ochiq oynalar: " + " | ".join(t for _, t in titles)[:800])
        return False
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.ShowWindow(h, 3)          # SW_MAXIMIZE
        pyautogui.press("alt")
        user32.SetForegroundWindow(h)
        time.sleep(0.6)
    except Exception as e:  # noqa
        log(f"   1C oynasini oldinga chiqarib bo'lmadi: {e}")
        return False
    return True


class Stopped(Exception):
    pass


class Failed(Exception):
    """Qadam bajarilmadi — sababi bilan."""


class Runner:
    def __init__(self, cfg, ui_ask, ui_status):
        self.cfg = cfg
        self.ask = ui_ask
        self.status = ui_status
        self.stop = threading.Event()
        self._kl = keyboard.Listener(on_press=self._on_key)

    def _on_key(self, key):
        if key == keyboard.Key.esc:
            self.stop.set()

    # ---------- asosiy yordamchilar ----------
    def log(self, text):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(os.path.join(CONFIG_DIR, "log.txt"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
        except OSError:
            pass

    def wait(self, sec):
        end = time.time() + sec * float(self.cfg.get("tezlik", 1.0))
        while time.time() < end:
            if self.stop.is_set():
                raise Stopped()
            time.sleep(0.05)

    def shot(self):
        try:
            return pyautogui.screenshot().convert("L").resize((240, 135))
        except Exception:  # noqa
            return None

    def wait_change(self, before, timeout=6.0, what=""):
        """Ekran o'zgarguncha kutish (oyna ochildi/yopildi). O'zgarmasa False."""
        if before is None:
            self.wait(1.5)
            return True
        end = time.time() + timeout * float(self.cfg.get("tezlik", 1.0))
        while time.time() < end:
            self.wait(0.25)
            now = self.shot()
            if now is None:
                return True
            diff = sum(1 for a, b in zip(before.getdata(), now.getdata()) if abs(a - b) > 25)
            if diff > 150:          # ~0.5% piksel o'zgardi
                self.wait(0.5)      # chizib bo'lishini kutish
                return True
        self.log(f"   ekran o'zgarmadi: {what}")
        return False

    def anchor_ok(self, name):
        a = self.cfg.get("anchors", {}).get(name)
        if not a:
            return True
        x, y = self.cfg["points"][ANCHORS[name]]
        try:
            cur = grab_patch(pyautogui.screenshot(), x, y)
        except Exception:  # noqa
            return True
        d = patch_diff(cur, patch_from_cfg(a))
        return d < 22

    def wait_anchor(self, name, present=True, timeout=10.0):
        """Belgi paydo bo'lguncha (yoki yo'qolguncha) kutish."""
        end = time.time() + timeout * float(self.cfg.get("tezlik", 1.0))
        while time.time() < end:
            if self.anchor_ok(name) == present:
                self.wait(0.4)
                return True
            self.wait(0.3)
        self.log(f"   belgi '{name}' {'chiqmadi' if present else 'yo`qolmadi'}")
        return False

    def click(self, name, double=False):
        x, y = self.cfg["points"][name]
        if double:
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.click(x, y)
        self.wait(0.35)

    def key(self, *keys):
        if self.stop.is_set():
            raise Stopped()
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        self.wait(0.2)

    def paste(self, text):
        pyperclip.copy(str(text))
        self.wait(0.2)
        pyautogui.hotkey("ctrl", "v")
        self.wait(0.35)

    def clear_text(self):
        self.key("end")
        self.key("shift", "home")
        self.key("delete")

    def read_field(self):
        """Fokusdagi maydon matnini o'qish (Ctrl+A, Ctrl+C). O'qib bo'lmasa None."""
        sentinel = "~~spes~~"
        pyperclip.copy(sentinel)
        self.wait(0.15)
        pyautogui.hotkey("ctrl", "a")
        self.wait(0.15)
        pyautogui.hotkey("ctrl", "c")
        self.wait(0.6)
        try:
            txt = pyperclip.paste()
        except Exception:  # noqa
            return None
        pyautogui.press("end")
        return None if txt == sentinel else " ".join(txt.split())

    def read_cell(self):
        """Ro'yxatda tanlangan katakni o'qish (Ctrl+C). O'qib bo'lmasa None."""
        sentinel = "~~spes~~"
        pyperclip.copy(sentinel)
        self.wait(0.15)
        pyautogui.hotkey("ctrl", "c")
        self.wait(0.7)
        try:
            txt = pyperclip.paste()
        except Exception:  # noqa
            return None
        return None if txt == sentinel else " ".join(txt.split())

    def checkpoint(self, text):
        if not self.ask(text):
            raise Stopped()

    # ---------- qadamlar ----------
    def open_new_doc(self):
        for attempt in (1, 2):
            self.status("Yangi накладная ochilyapti…")
            self.click("prodaja")
            self.wait(1.5)
            self.click("real_link")
            self.wait(3.0)                      # ro'yxat ochilsin
            self.click("real_btn")
            self.wait(1.5)                      # menyu ochilsin
            self.click("tovary_nakl")
            if self.wait_anchor("doc", True, 12):
                self.wait(1.0)
                return
            self.log(f"   yangi накладная ochilmadi (urinish {attempt})")
            self.key("esc")                     # ochiq qolgan menyuni yopish
            self.wait(1.0)
        raise Failed("Yangi накладная ochilmadi. 1C'da Продажи → Реализация ro'yxati ochiladimi — tekshiring, "
                     "yoki «O'rgatish» ni qaytadan qiling.")

    def fill_field(self, name, text, settle=1.5, label=""):
        for attempt in (1, 2):
            self.click(name)
            self.key("shift", "f4")          # 1C: maydonni tozalash
            self.paste(text)
            self.wait(settle)
            self.key("tab")
            self.wait(1.0)
            self.click(name)
            got = self.read_field()
            self.key("tab")
            self.wait(0.4)
            self.log(f"   {label}: yozildi {text!r}, 1C'da {got!r}")
            if got is None or got.strip():
                return got
            self.log(f"   {label}: bo'sh qoldi, qayta urinish {attempt}")
        raise Failed(f"«{label}» maydoniga yozib bo'lmadi (bo'sh qoldi).")

    def add_item(self, i, n, it):
        self.status(f"Mahsulot {i}/{n}: {it.name}")
        if not self.anchor_ok("podbor"):
            raise Failed("Подбор oynasi ko'rinmayapti — to'xtatildi.")
        # qidiruv
        self.click("qidiruv")
        self.clear_text()
        b = self.shot()
        self.paste(it.search)
        self.key("enter")
        self.wait_change(b, 4, "qidiruv natijasi")
        self.wait(0.8)
        # topilganini tekshirish
        self.click("first_row")
        found = self.read_cell()
        self.log(f"[{i}] qidiruv {it.search!r} -> 1C: {found!r}")
        if found is not None and not same_product(it.search, found):
            self.manual(i, n, it, f"1C'da birinchi chiqqan: «{found or '(hech narsa topilmadi)'}»")
            return
        # miqdor oynasi
        self.click("first_row", double=True)
        if not self.wait_anchor("dlg", True, 6):
            self.manual(i, n, it, "Mahsulot ikki marta bosildi, lekin Количество/Цена/Сумма oynasi ochilmadi.")
            return
        for fld, val in (("dlg_qty", it.qty_text), ("dlg_price", it.price_text), ("dlg_sum", it.amount_text)):
            self.click(fld)
            self.clear_text()
            self.paste(val)
            self.key("tab")
            self.wait(0.4)
        # summa to'g'ri turganini tekshirish
        self.click("dlg_sum")
        got = self.read_field()
        self.log(f"[{i}] oynada summa: {got!r} (kerak {it.amount_text})")
        if got is not None and not num_equal(got, it.amount_text):
            self.click("dlg_sum")
            self.clear_text()
            self.paste(it.amount_text)
            self.key("tab")
            self.wait(0.4)
        self.click("dlg_ok")
        if not self.wait_anchor("dlg", False, 5):
            self.key("enter")
            self.wait(1.0)
        if not self.wait_anchor("podbor", True, 6):
            raise Failed(f"{i}-mahsulotdan keyin Подбор oynasi ko'rinmay qoldi.")

    def manual(self, i, n, it, why):
        self.log(f"[{i}] QO'LDA: {why}")
        pyperclip.copy(it.amount_text)
        self.checkpoint(
            f"{i}/{n}: «{it.name}» avtomatik kiritilmadi.\n{why}\n\n"
            f"Shu mahsulotni 1C Подбор'da O'ZINGIZ kiriting:\n"
            f"   Количество: {it.qty_text}\n   Цена: {it.price_text}\n"
            f"   Сумма: {it.amount_text}  (nusxalandi — Ctrl+V)\n\n"
            "Keyin «Davom» bosing — dastur keyingi mahsulotga o'tadi.")

    # ---------- butun ish ----------
    def run(self, spec, date_text, items):
        self._kl.start()
        self.log(f"=== BOSHLANDI: spes №{spec.spec_no}, {spec.buyer_name}, {len(items)} ta mahsulot")
        try:
            self.status("1C oynasi qidirilyapti…")
            if not activate_1c(self.log):
                self.log("   1C oynasi avtomatik topilmadi — davom etamiz (1C ekranda turibdi deb)")
            self.wait(1.0)
            self.open_new_doc()

            if not self.anchor_ok("doc"):
                raise Failed("Накладная oynasi ko'rinmayapti — hech narsa yozilmadi.")
            self.status("Sana…")
            g_date = self.fill_field("date", date_text, 0.3, "Sana")
            self.status("Kontragent (INN bo'yicha)…")
            g_k = self.fill_field("kontragent", spec.buyer_inn, 2.5, "Kontragent")
            self.status("Shartnoma…")
            g_d = self.fill_field("dogovor", spec.contract_no, 2.0, "Shartnoma")
            self.status("Склад…")
            g_s = self.fill_field("sklad", self.cfg["sklad_nomi"], 1.5, "Склад")

            def show(v):
                return "(o'qib bo'lmadi)" if v is None else v
            self.checkpoint(
                "Sarlavha to'ldirildi. 1C'da tekshiring:\n\n"
                f"• Sana: {show(g_date)}\n"
                f"• Kontragent: {show(g_k)}\n    (kerak: {spec.buyer_name}, INN {spec.buyer_inn})\n"
                f"• Shartnoma: {show(g_d)}\n    (kerak: {spec.contract_no} dan {spec.contract_date})\n"
                f"• Склад: {show(g_s)}\n\n"
                "Noto'g'ri bo'lsa — 1C'da qo'lda tuzating (kontragent yo'q bo'lsa yarating), "
                "keyin «Davom».")

            self.status("Подбор ochilyapti…")
            if not self.anchor_ok("doc"):
                raise Failed("Накладная oynasi ko'rinmayapti — Подбор bosilmadi.")
            self.click("podbor")
            if not self.wait_anchor("podbor", True, 12):
                raise Failed("«Подбор» bosildi, lekin Подбор oynasi ochilmadi.")
            self.wait(0.8)

            n = len(items)
            for i, it in enumerate(items, 1):
                self.add_item(i, n, it)
                if self.cfg.get("qadamma_qadam") and i < n:
                    self.checkpoint(
                        f"{i}/{n}: «{it.name}»\n{it.qty_text} kg, summa {it.amount_text}\n\n"
                        "Pastdagi «Подобранные позиции» ro'yxatiga to'g'ri tushdimi?\n"
                        "To'g'ri bo'lsa «Davom». Xato bo'lsa — 1C'da tuzatib, keyin «Davom».")

            self.status("Hujjatga o'tkazilyapti…")
            if not self.anchor_ok("podbor"):
                raise Failed("Подбор oynasi ko'rinmayapti — «Перенести в документ» bosilmadi.")
            self.click("perenesti")
            self.wait_anchor("podbor", False, 8)
            self.log("=== TUGADI")
            return True
        except pyautogui.FailSafeException:
            raise Stopped()
        except Failed as e:
            self.log(f"!!! TO'XTADI: {e}")
            raise
        finally:
            self._kl.stop()


def capture_click(on_point, ignore_rect=None):
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
