#!/usr/bin/env python3
"""Pokémon 30th Celebration Stock-Bot.

Prüft regelmäßig (Standard: jede Minute) die in config.json eingetragenen Shops
auf englische Pokémon-TCG-"30th Celebration"-Produkte und schickt eine E-Mail,
sobald ein Produkt (wieder) auf Lager ist.

Benötigt nur die Python-Standardbibliothek (Python 3.9+).

E-Mail-Zugangsdaten kommen aus Umgebungsvariablen:
  SMTP_HOST      (Standard: smtp.gmail.com)
  SMTP_PORT      (Standard: 465 = SSL; 587 = STARTTLS)
  SMTP_USER      z.B. deine.adresse@gmail.com
  SMTP_PASSWORD  bei Gmail ein App-Passwort, NICHT dein normales Passwort
  MAIL_TO        Empfänger (Standard: SMTP_USER)

Aufruf:
  python3 bot.py                 # läuft endlos, prüft jede Minute
  python3 bot.py --once          # genau ein Durchlauf (zum Testen)
  python3 bot.py --test-mail     # schickt eine Test-Mail und beendet sich
  python3 bot.py --duration 350  # läuft 350 Minuten, dann Ende (für GitHub Actions)
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import os
import random
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.json"
DEFAULT_STATE = HERE / "state.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

IN_STOCK_SCHEMA = ("instock", "limitedavailability", "onlineonly", "instoreonly")
PREORDER_SCHEMA = ("preorder", "presale", "backorder")
OUT_OF_STOCK_SCHEMA = ("outofstock", "soldout", "discontinued")

DEFAULT_OUT_OF_STOCK_WORDS = [
    "ausverkauft", "nicht verfügbar", "nicht vorrätig", "nicht auf lager",
    "derzeit nicht lieferbar", "sold out", "out of stock", "currently unavailable",
    "benachrichtigen, wenn verfügbar", "notify me when available",
]
DEFAULT_IN_STOCK_WORDS = [
    "in den warenkorb", "add to cart", "add to basket", "auf lager",
    "sofort lieferbar", "sofort verfügbar", "in stock",
]


@dataclass
class Product:
    shop: str
    title: str
    url: str
    available: bool
    price: str = ""
    note: str = ""  # z.B. "Vorbestellung"

    @property
    def key(self) -> str:
        return f"{self.shop}|{self.url.split('?')[0]}"


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------- HTTP

def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        charset = resp.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")


# ----------------------------------------------------------------- Filter-Logik

class TitleFilter:
    def __init__(self, cfg: dict):
        f = cfg.get("filter", {})
        self.include = re.compile(f.get("include_regex", r"30th|30 ?jahre"), re.I)
        self.exclude = re.compile(f["exclude_regex"], re.I) if f.get("exclude_regex") else None
        self.english = re.compile(
            f.get("english_regex", r"\b(englisch|english|eng|en)\b"), re.I
        )

    def matches(self, title: str, require_english_marker: bool) -> bool:
        if not self.include.search(title):
            return False
        if self.exclude and self.exclude.search(title):
            return False
        if require_english_marker and not self.english.search(title):
            return False
        return True


# ------------------------------------------------------------- Shopify-Shops

def check_shopify(shop: dict) -> list[Product]:
    """Nutzt die öffentliche Shopify-Suche (/search/suggest.json).

    Liefert pro Produkt ein zuverlässiges "available"-Feld.
    """
    base = shop["url"].rstrip("/")
    found: dict[str, Product] = {}
    for query in shop.get("queries", ["30th Celebration"]):
        params = urllib.parse.urlencode({
            "q": query,
            "resources[type]": "product",
            "resources[limit]": 10,
            "resources[options][unavailable_products]": "last",
        })
        data = json.loads(fetch(f"{base}/search/suggest.json?{params}"))
        for p in parse_shopify_suggest(data, shop["name"], base):
            found[p.key] = p
    return list(found.values())


def parse_shopify_suggest(data: dict, shop_name: str, base: str) -> list[Product]:
    products = data.get("resources", {}).get("results", {}).get("products", [])
    out = []
    for p in products:
        url = urllib.parse.urljoin(base + "/", p.get("url", ""))
        price = p.get("price") or p.get("price_min") or ""
        tags = " ".join(p.get("tags", []) or []).lower()
        out.append(Product(
            shop=shop_name,
            title=html.unescape(p.get("title", "")).strip(),
            url=url.split("?")[0],
            available=bool(p.get("available")),
            price=str(price),
            note="Vorbestellung" if "preorder" in tags or "vorbestellung" in tags else "",
        ))
    return out


# ------------------------------------------------------- Einzelne Produktseite

JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)
TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I)
HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def page_availability(page: str, shop: dict) -> tuple[bool | None, str]:
    """Gibt (verfügbar?, Hinweis) zurück. None = konnte nicht ermittelt werden."""
    states = []
    for block in JSONLD_RE.findall(page):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            av = node.get("availability")
            if isinstance(av, str):
                states.append(av.rsplit("/", 1)[-1].lower())
    if states:
        if any(s in IN_STOCK_SCHEMA for s in states):
            return True, ""
        if any(s in PREORDER_SCHEMA for s in states):
            return True, "Vorbestellung"
        if any(s in OUT_OF_STOCK_SCHEMA for s in states):
            return False, ""

    # Fallback: Schlüsselwörter im sichtbaren Text
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text)).lower()
    out_words = shop.get("out_of_stock_words", DEFAULT_OUT_OF_STOCK_WORDS)
    in_words = shop.get("in_stock_words", DEFAULT_IN_STOCK_WORDS)
    if any(w.lower() in text for w in out_words):
        return False, ""
    if any(w.lower() in text for w in in_words):
        return True, ""
    return None, ""


def page_title(page: str) -> str:
    m = TITLE_RE.search(page) or HTML_TITLE_RE.search(page)
    return html.unescape(m.group(1)).strip() if m else ""


def check_page(shop: dict) -> list[Product]:
    page = fetch(shop["url"])
    available, note = page_availability(page, shop)
    if available is None:
        raise RuntimeError("Verfügbarkeit nicht erkennbar (evtl. Bot-Schutz oder neues Layout)")
    return [Product(
        shop=shop["name"],
        title=shop.get("title") or page_title(page) or shop["url"],
        url=shop["url"],
        available=available,
        note=note,
    )]


# ---------------------------------------------------------- WooCommerce-Shops

def check_woocommerce(shop: dict) -> list[Product]:
    """Nutzt die öffentliche WooCommerce Store API (liefert is_in_stock)."""
    base = shop["url"].rstrip("/")
    found: dict[str, Product] = {}
    for query in shop.get("queries", ["30th Celebration"]):
        params = urllib.parse.urlencode({"search": query, "per_page": 20})
        data = json.loads(fetch(f"{base}/wp-json/wc/store/v1/products?{params}"))
        for p in parse_woocommerce(data, shop["name"]):
            found[p.key] = p
    return list(found.values())


def parse_woocommerce(data: list, shop_name: str) -> list[Product]:
    if not isinstance(data, list):
        raise ValueError("keine WooCommerce-Antwort")
    out = []
    for p in data:
        prices = p.get("prices") or {}
        price = ""
        if prices.get("price"):
            minor = int(prices.get("currency_minor_unit", 2))
            price = f"{int(prices['price']) / 10 ** minor:.2f} {prices.get('currency_code', '')}".strip()
        out.append(Product(
            shop=shop_name,
            title=html.unescape(re.sub(r"<[^>]+>", "", p.get("name", ""))).strip(),
            url=p.get("permalink", ""),
            available=bool(p.get("is_in_stock")) and p.get("is_purchasable", True) is not False,
            price=price,
        ))
    return out


# ------------------------------------------- Beliebiger Shop über Suchseite

ANCHOR_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def find_product_links(page: str, page_url: str, include: re.Pattern) -> list[str]:
    """Sucht auf einer Suchergebnisseite Links, die nach einem passenden Produkt aussehen."""
    host = urllib.parse.urlparse(page_url).netloc
    links: dict[str, None] = {}
    for href, inner in ANCHOR_RE.findall(page):
        url = urllib.parse.urljoin(page_url, html.unescape(href))
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc != host or parsed.scheme not in ("http", "https"):
            continue
        text = html.unescape(re.sub(r"<[^>]+>", " ", inner))
        slug = re.sub(r"[-_/+]", " ", urllib.parse.unquote(parsed.path))
        if include.search(f"{text} {slug}"):
            links[url.split("#")[0]] = None
    return list(links)


def check_search(shop: dict, include: re.Pattern | None = None) -> list[Product]:
    """Öffnet die Suchseite des Shops, folgt passenden Produktlinks und
    liest auf jeder Produktseite den Lagerstatus aus."""
    include = include or re.compile(r"30th|30 ?jahre", re.I)
    links: list[str] = []
    for query in shop.get("queries", ["30th Celebration"]):
        url = shop["search_url"].replace("{q}", urllib.parse.quote_plus(query))
        for link in find_product_links(fetch(url), url, include):
            if link not in links:
                links.append(link)
    out = []
    for link in links[: shop.get("max_products", 8)]:
        try:
            page = fetch(link)
        except Exception as e:  # noqa: BLE001
            log(f"   {shop['name']}: {link} nicht ladbar ({e})")
            continue
        available, note = page_availability(page, shop)
        if available is None:
            log(f"   {shop['name']}: Lagerstatus auf {link} nicht erkennbar")
            continue
        out.append(Product(shop=shop["name"], title=page_title(page) or link,
                           url=link, available=available, note=note))
    return out


# ------------------------------------------------- Automatische Erkennung

def check_auto(shop: dict, include: re.Pattern | None = None) -> list[Product]:
    """Probiert Shopify, dann WooCommerce, dann die Suchseite (search_url).
    Was einmal funktioniert hat, wird für die folgenden Durchläufe gemerkt."""
    detected = shop.get("_detected")
    if detected:
        return _run_checker(detected, shop, include)
    order = ["shopify", "woocommerce"] + (["search"] if shop.get("search_url") else [])
    errors = []
    for kind in order:
        try:
            products = _run_checker(kind, shop, include)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{kind}: {type(e).__name__}")
            continue
        shop["_detected"] = kind
        log(f"   {shop['name']}: erkannt als '{kind}'")
        return products
    raise RuntimeError("kein passender Shop-Typ (" + ", ".join(errors) + ")")


def _run_checker(kind: str, shop: dict, include: re.Pattern | None) -> list[Product]:
    if kind == "search":
        return check_search(shop, include)
    return CHECKERS[kind](shop)


CHECKERS = {
    "shopify": check_shopify,
    "woocommerce": check_woocommerce,
    "page": check_page,
    "search": check_search,
    "auto": check_auto,
}


# ------------------------------------------------------------------- E-Mail

def send_mail(subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    to = os.environ.get("MAIL_TO") or user
    if not (user and password and to):
        log("!! Keine E-Mail-Zugangsdaten gesetzt (SMTP_USER / SMTP_PASSWORD) – Mail nur hier ausgegeben:")
        print(f"--- {subject} ---\n{body}\n---", flush=True)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(body)

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)
    log(f"E-Mail gesendet an {to}: {subject}")


def format_mail(products: list[Product]) -> tuple[str, str]:
    if len(products) == 1:
        subject = f"🟢 AUF LAGER: {products[0].title} ({products[0].shop})"
    else:
        subject = f"🟢 {len(products)} Pokémon 30th Celebration Produkte auf Lager!"
    lines = ["Folgende Produkte sind gerade verfügbar:\n"]
    for p in products:
        extra = " · ".join(x for x in (p.price, p.note) if x)
        lines.append(f"• {p.title}\n  Shop: {p.shop}{'  (' + extra + ')' if extra else ''}\n  {p.url}\n")
    lines.append(f"Gefunden am {datetime.now():%d.%m.%Y um %H:%M:%S}. Schnell sein! 🏃")
    return subject, "\n".join(lines)


# ------------------------------------------------------------------- Zustand

def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------ Durchlauf

def run_once(cfg: dict, state: dict, title_filter: TitleFilter) -> list[Product]:
    """Prüft alle Shops und gibt Produkte zurück, die NEU auf Lager sind."""
    newly_available = []
    for shop in cfg["shops"]:
        if not shop.get("enabled", True):
            continue
        kind = shop.get("type", "auto")
        if kind not in CHECKERS:
            log(f"!! {shop['name']}: unbekannter Typ '{kind}'")
            continue
        try:
            if kind in ("search", "auto"):
                products = CHECKERS[kind](shop, title_filter.include)
            else:
                products = CHECKERS[kind](shop)
        except urllib.error.HTTPError as e:
            log(f"!! {shop['name']}: HTTP {e.code}")
            continue
        except Exception as e:  # noqa: BLE001 – ein kaputter Shop darf den Bot nicht stoppen
            log(f"!! {shop['name']}: {type(e).__name__}: {e}")
            continue

        # Einzelne Produktseiten sind bereits gezielt ausgewählt – kein Titel-Filter nötig.
        if kind != "page":
            need_en = shop.get("require_english_marker", False)
            products = [p for p in products if title_filter.matches(p.title, need_en)]

        in_stock = [p for p in products if p.available]
        log(f"{shop['name']}: {len(products)} passende Produkte, {len(in_stock)} auf Lager")

        for p in products:
            was_available = state.get(p.key, {}).get("available", False)
            if p.available and not was_available:
                newly_available.append(p)
            state[p.key] = {
                "available": p.available,
                "title": p.title,
                "seen": datetime.now().isoformat(timespec="seconds"),
            }
    return newly_available


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--interval", type=int, help="Sekunden zwischen den Prüfungen (überschreibt config)")
    ap.add_argument("--once", action="store_true", help="nur ein Durchlauf")
    ap.add_argument("--duration", type=float, help="nach so vielen Minuten beenden")
    ap.add_argument("--test-mail", action="store_true", help="Test-Mail senden und beenden")
    args = ap.parse_args()

    if args.test_mail:
        send_mail("✅ Test vom Pokémon Stock-Bot", "Wenn du das liest, funktioniert der E-Mail-Versand.")
        return 0

    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    interval = args.interval or cfg.get("interval_seconds", 60)
    title_filter = TitleFilter(cfg)
    state = load_state(args.state)
    deadline = time.time() + args.duration * 60 if args.duration else None

    log(f"Bot gestartet – {len(cfg['shops'])} Shops, Intervall {interval}s")
    while True:
        started = time.time()
        newly = run_once(cfg, state, title_filter)
        save_state(args.state, state)
        if newly:
            subject, body = format_mail(newly)
            try:
                send_mail(subject, body)
            except Exception as e:  # noqa: BLE001
                log(f"!! E-Mail fehlgeschlagen: {e}")
                # Beim nächsten Durchlauf erneut versuchen
                for p in newly:
                    state[p.key]["available"] = False
                save_state(args.state, state)

        if args.once:
            return 0
        # kleiner Zufallsanteil, damit die Anfragen nicht wie ein Uhrwerk aussehen
        sleep_for = max(5.0, interval - (time.time() - started) + random.uniform(-5, 5))
        if deadline and time.time() + sleep_for > deadline:
            log("Laufzeit erreicht – beende.")
            return 0
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Beendet.")
