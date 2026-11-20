"""Mexmash spetsifikatsiya PDF faylini o'qish (Excel'dan saqlangan PDF)."""
import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

import pdfplumber

SELLER_INN = "200047118"  # Mexmash MChJ — o'zimizning INN, kontragent emas

MONTHS = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6,
    "iyul": 7, "avgust": 8, "sentabr": 9, "sentyabr": 9, "oktabr": 10,
    "oktyabr": 10, "noyabr": 11, "dekabr": 12,
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

TWO = Decimal("0.01")


def num(s):
    """'2 1 800,89' -> Decimal('21800.89'); bo'sh bo'lsa None."""
    if s is None:
        return None
    s = re.sub(r"\s+", "", str(s)).replace("%", "").replace(",", ".")
    if not s or not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return None
    return Decimal(s)


def clean_name(s):
    s = (s or "").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def search_key(name):
    """Подбор'da qidirish uchun qisqa kalit: o'lcham (3,5х16) + 'мелкий/крупный'."""
    n = name.lower()
    size = re.search(r"\d+[.,]?\d*\s*[хx×]\s*\d+[.,]?\d*", n)
    key = re.sub(r"\s+", "", size.group(0)).replace("x", "х") if size else ""
    for w in ("мелкий", "крупный", "острый", "сверлом"):
        if w in n:
            key += " " + w
    ral = re.search(r"ral\s*\d+", n)
    if ral:
        key += " " + ral.group(0).upper()
    return key.strip() or name


def search_text(name):
    """1C Подбор qidiruvi uchun matn: nomning o'lchamdan boshlangan qismi
    ('Шурупы размер 3,5х16 мелкий шаг' -> '3,5х16 мелкий шаг')."""
    n = re.sub(r"\s+", " ", name).strip()
    m = re.search(r"\d+[.,]?\d*\s*[хx×]\s*\d+", n)
    return n[m.start():] if m else n


@dataclass
class Item:
    no: int
    name: str
    unit: str
    qty: Decimal
    price: Decimal      # spetsifikatsiyadagi narx (QQSsiz)
    amount: Decimal     # yetkazib berish qiymati (QQSsiz) — 1C'ga shu qo'yiladi
    vat_rate: str
    vat: Decimal
    total: Decimal      # QQS bilan
    search: str = ""    # Подбор'da qidiriladigan matn (o'zgartirsa bo'ladi)

    def __post_init__(self):
        if not self.search:
            self.search = search_text(self.name)

    @property
    def qty_text(self):
        return plain(self.qty, 3).rstrip("0").rstrip(",")

    @property
    def amount_text(self):
        return plain(self.amount)

    @property
    def key(self):
        return search_key(self.name)

    @property
    def needs_fix(self):
        """1C narx x miqdor spetsifikatsiya summasiga teng chiqmasa — summani qo'lda tuzatish kerak."""
        return (self.price_1c * self.qty).quantize(TWO, ROUND_HALF_UP) != self.amount

    @property
    def price_1c(self):
        """1C uchun narx: summa / miqdor, 2 xonagacha."""
        if self.qty:
            return (self.amount / self.qty).quantize(TWO, ROUND_HALF_UP)
        return self.price


@dataclass
class Spec:
    file: str
    spec_no: str = ""
    contract_no: str = ""
    contract_date: str = ""   # dd.mm.yyyy
    buyer_name: str = ""
    buyer_inn: str = ""
    items: list = field(default_factory=list)
    jami_qty: Decimal = None
    jami_total: Decimal = None
    warnings: list = field(default_factory=list)

    @property
    def sum_amount(self):
        return sum((i.amount for i in self.items), Decimal(0))

    @property
    def sum_vat(self):
        return sum((i.vat for i in self.items), Decimal(0))

    @property
    def sum_total(self):
        return sum((i.total for i in self.items), Decimal(0))

    @property
    def sum_qty(self):
        return sum((i.qty for i in self.items), Decimal(0))


def _parse_header(text, spec):
    m = re.search(r"(\d+)\s*-?\s*sonli\s+SPES", text, re.I)
    if m:
        spec.spec_no = m.group(1)

    m = re.search(r"([^\s_][^\n]*?)_*\s*-\s*sonli\s+shartnoma", text, re.I)
    if m:
        spec.contract_no = m.group(1).strip(" _")

    m = re.search(r"(\d{4})\s*yil\s*[“\"«']?_*\s*(\d{1,2})\s*_*[”\"»']?\s*_*\s*([A-Za-zА-Яа-яЁёʻ’']+|\d{1,2})\s*_*\s*dagi",
                  text, re.I)
    if m:
        year, day, mon = m.group(1), int(m.group(2)), m.group(3)
        if mon.isdigit():
            month = int(mon)
        else:
            low = mon.lower()
            month = next((v for k, v in MONTHS.items() if low.startswith(k[:3]) and k.startswith(low[:3])), 0)
        if month:
            spec.contract_date = f"{day:02d}.{month:02d}.{year}"
    if not spec.contract_date:
        spec.warnings.append("Shartnoma sanasi o'qilmadi — qo'lda tekshiring.")

    inns = [x for x in re.findall(r"STIR\s*:?\D{0,12}?(\d{14}|\d{9})", text) if x != SELLER_INN]
    if inns:
        spec.buyer_inn = inns[0]
    else:
        spec.warnings.append("Kontragent INN (STIR) topilmadi.")

    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if "SOTIB OLUVCH" in ln.upper() and i + 1 < len(lines):
            nxt = lines[i + 1]
            nxt = re.sub(r'^\s*["“]?Mexmash["”]?\s*(MChJ|MCHJ|МЧЖ)?', "", nxt, flags=re.I).strip()
            spec.buyer_name = nxt
            break


def parse_spec(path):
    spec = Spec(file=path)
    with pdfplumber.open(path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        rows = []
        for p in pdf.pages:
            for t in p.extract_tables():
                rows.extend(t)
    text = re.sub(r"\(cid:\d+\)", " ", text)
    _parse_header(text, spec)

    for r in rows:
        if not r or len(r) < 9:
            continue
        r = list(r) + [None] * (10 - len(r))
        first = (r[0] or "").strip()
        name = clean_name(r[1])
        if name.lower().startswith("jami"):
            spec.jami_qty = num(r[3])
            spec.jami_total = num(r[8])
            continue
        if not first.isdigit() or not name:
            continue
        qty, price, amount, vat, total = num(r[3]), num(r[4]), num(r[5]), num(r[7]), num(r[8])
        if qty is None or amount is None:
            spec.warnings.append(f"{first}-qator to'liq o'qilmadi: {name}")
            continue
        spec.items.append(Item(int(first), name, (r[2] or "").strip(), qty, price or Decimal(0),
                               amount, (r[6] or "").strip(), vat or Decimal(0), total or Decimal(0)))

    m = re.search(r"umumiy[^\d]*([\d\s]+,\d{2})\s*so", text)
    if spec.jami_total is None and m:
        spec.jami_total = num(m.group(1))

    if not spec.items:
        spec.warnings.append("Mahsulotlar jadvali topilmadi.")
    if spec.jami_total is not None and spec.items and spec.sum_total != spec.jami_total:
        spec.warnings.append(f"Qatorlar yig'indisi ({fmt(spec.sum_total)}) 'Jami' ({fmt(spec.jami_total)}) bilan mos emas!")
    if spec.jami_qty is not None and spec.items and spec.sum_qty != spec.jami_qty:
        spec.warnings.append(f"Miqdorlar yig'indisi ({spec.sum_qty}) 'Jami' ({spec.jami_qty}) bilan mos emas!")
    for it in spec.items:
        if it.amount + it.vat != it.total:
            spec.warnings.append(f"{it.no}-qator: summa + QQS ≠ jami.")
    return spec


def fmt(d, places=2):
    if d is None:
        return ""
    q = Decimal(1).scaleb(-places)
    s = f"{Decimal(d).quantize(q, ROUND_HALF_UP):,.{places}f}"
    return s.replace(",", " ").replace(".", ",")


def fmt_qty(d):
    s = fmt(d, 3).rstrip("0").rstrip(",")
    return s


def plain(d, places=2):
    """1C/Excel'ga qo'yish uchun: 6540267,86 (bo'shliqsiz, vergul bilan)."""
    q = Decimal(1).scaleb(-places)
    return f"{Decimal(d).quantize(q, ROUND_HALF_UP):.{places}f}".replace(".", ",")


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        s = parse_spec(f)
        print("==", f)
        print(f" Spes №{s.spec_no} | Shartnoma {s.contract_no} dan {s.contract_date} | {s.buyer_name} | INN {s.buyer_inn}")
        for it in s.items:
            print(f"  {it.no:>2} {it.name:<55} [{it.key}] {fmt_qty(it.qty):>8} {fmt(it.price):>10} {fmt(it.amount):>15} {fmt(it.total):>15}  1C narx {plain(it.price_1c)} {'TUZAT' if it.needs_fix else ''}")
        print(f"  JAMI: qatorlar {fmt(s.sum_total)} / spes {fmt(s.jami_total)} | QQSsiz {fmt(s.sum_amount)}")
        for w in s.warnings:
            print("  !!", w)
