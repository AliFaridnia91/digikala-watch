#!/usr/bin/env python3
"""Watch a Digikala product and alert when a chosen variant is in stock.

Usage:
  python3 dk_watch.py <product URL or id> --list
  python3 dk_watch.py <product URL or id> --variant "مشکی" [--variant "256"] [--max-price 45000000] [--interval 120]

--variant may be given several times; a variant matches only if every text
matches one of its options (color, size, storage, ...). Prices are Toman.
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.digikala.com/v2/product/{}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
           "Accept": "application/json"}


def product_id(arg):
    m = re.search(r"dkp-(\d+)", arg) or re.fullmatch(r"\s*(\d+)\s*", arg)
    if not m:
        sys.exit(f"Could not find a product id in: {arg}")
    return m.group(1)


# Keeps cookies between requests, for sites that set one on a redirect.
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())


def fetch(pid):
    req = urllib.request.Request(API.format(pid), headers=HEADERS)
    try:
        with OPENER.open(req, timeout=30) as r:
            return json.load(r)["data"]["product"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {e.url}, Location: {e.headers.get('Location')}, "
                           f"body: {e.read(300)!r}") from None


def options(variant):
    """All option labels of a variant, e.g. ['مشکی', '256 گیگابایت']."""
    labels = []
    for t in variant.get("themes") or []:
        v = t.get("value") or {}
        if v.get("title"):
            labels.append(v["title"])
    for key in ("color", "size"):
        if (variant.get(key) or {}).get("title"):
            labels.append(variant[key]["title"])
    return list(dict.fromkeys(labels))


def norm(s):
    # Treat Arabic/Persian letter forms and digits alike, ignore spaces and case.
    s = s.translate(str.maketrans("يك۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "یک01234567890123456789"))
    return re.sub(r"[\s‌]+", "", s).lower()


def matches(variant, wanted, excluded=()):
    opts = [norm(o) for o in options(variant)]
    return all(any(norm(w) in o for o in opts) for w in wanted) and \
        not any(norm(x) in o for x in excluded for o in opts)


def in_stock(variant):
    return variant.get("status") == "marketable" and \
        (variant.get("price") or {}).get("marketable_stock", 1) != 0


def toman(rial):
    return f"{rial // 10:,}"


def telegram(text):
    """Send text with the bot in TELEGRAM_BOT_TOKEN. If TELEGRAM_CHAT_ID is not set,
    send to whoever last messaged the bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    api = f"https://api.telegram.org/bot{token}/"
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat:
        with urllib.request.urlopen(api + "getUpdates", timeout=30) as r:
            updates = json.load(r).get("result") or []
        chats = [(u.get("message") or u.get("my_chat_member") or {}).get("chat", {}).get("id") for u in updates]
        chats = [c for c in chats if c]
        if not chats:
            raise RuntimeError("No chat found: open your bot in Telegram and press Start (or send it any message).")
        chat = chats[-1]
        print(f"Using Telegram chat id {chat} (save it as TELEGRAM_CHAT_ID; the bot forgets it after 24 hours).")
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(api + "sendMessage", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("ok", False)


def notify(title, msg, url=""):
    print("\a", end="", flush=True)
    try:
        if telegram(f"{title}\n{msg}\n{url}".strip()):
            print("Telegram message sent.")
    except Exception as e:
        print(f"Telegram failed: {e}")
    if sys.platform == "darwin":
        q = lambda s: json.dumps(s, ensure_ascii=False)
        script = f'display notification {q(msg)} with title {q(title)} sound name "Glass"'
        subprocess.run(["osascript", "-e", script], check=False)
        subprocess.run(["say", "Digikala item is available"], check=False)


def track_new(a, pid, url):
    """Keep watching; alert for each variant that appears in stock. Returns 0 at --duration."""
    try:
        with open(a.track_new, encoding="utf-8") as f:
            seen = set(json.load(f)["in_stock"])
    except (OSError, ValueError, KeyError):
        seen = None  # first run: record what is on sale now, alert from then on
    print(f"Watching {url} for newly available variants, every {a.interval}s. Ctrl+C to stop.")
    deadline = time.time() + a.duration if a.duration else None
    while True:
        stamp = time.strftime("%H:%M:%S")
        try:
            p = fetch(pid)
            cheapest = {}
            for v in p.get("variants") or []:
                if in_stock(v) and matches(v, a.variant, a.exclude):
                    key = " / ".join(options(v)) or "(no options)"
                    if key not in cheapest or v["price"]["selling_price"] < cheapest[key]["price"]["selling_price"]:
                        cheapest[key] = v
            now = set(cheapest)
            if seen is None:
                print(f"[{stamp}] starting point, on sale now: {', '.join(sorted(now)) or 'nothing'}")
            else:
                new = sorted(now - seen)
                if new:
                    lines = [f"{k} - {toman(cheapest[k]['price']['selling_price'])} T ({cheapest[k]['seller']['title']})"
                             for k in new]
                    print(f"[{stamp}] NEW: " + "; ".join(lines))
                    notify("Digikala: new variant available!", "\n".join(lines), url)
                else:
                    print(f"[{stamp}] nothing new ({len(now)} on sale)")
            if now != seen:
                seen = now
                with open(a.track_new, "w", encoding="utf-8") as f:
                    json.dump({"in_stock": sorted(seen)}, f, ensure_ascii=False, indent=1)
        except Exception as e:  # network hiccups, rate limits: keep going
            print(f"[{stamp}] error: {e}")
        if a.once or (deadline and time.time() + a.interval > deadline):
            return 0
        time.sleep(a.interval + random.randint(0, 5))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("product", help="product URL (…/dkp-12345/…) or id")
    ap.add_argument("--variant", action="append", default=[], help="text to match in the variant's options")
    ap.add_argument("--exclude", action="append", default=[], help="skip variants whose options contain this text")
    ap.add_argument("--max-price", type=int, help="only alert at or below this price (Toman)")
    ap.add_argument("--interval", type=int, default=120, help="seconds between checks (default 120)")
    ap.add_argument("--list", action="store_true", help="show the variants currently on sale and exit")
    ap.add_argument("--once", action="store_true", help="check once and exit (code 0 = found)")
    ap.add_argument("--duration", type=int, help="give up after this many seconds (exit code 1)")
    ap.add_argument("--test-alert", action="store_true", help="send a test alert and exit")
    ap.add_argument("--track-new", metavar="STATE_FILE",
                    help="alert whenever a variant comes in stock that was not on sale at the previous check; "
                         "the last seen variants are kept in STATE_FILE")
    a = ap.parse_args()
    pid = product_id(a.product)
    url = f"https://www.digikala.com/product/dkp-{pid}/"

    if a.test_alert:
        notify("Digikala watcher: test", "If you see this, alerts work.", url)
        return

    if a.list:
        p = fetch(pid)
        print(p.get("title_fa", ""), "-", url)
        print("All options of this product:", ", ".join(c["title"] for c in p.get("colors") or []) or "-")
        for v in p.get("variants") or []:
            print(f"  {' / '.join(options(v)) or '(no options)':30} {toman(v['price']['selling_price']):>14} T  "
                  f"{v['seller']['title']}  [{v['status']}]")
        return

    if a.track_new:
        return track_new(a, pid, url)

    if not a.variant:
        sys.exit("Give --variant (or use --list to see the options).")

    print(f"Watching {url} for: {' + '.join(a.variant)}"
          + (f" (not {', '.join(a.exclude)})" if a.exclude else "")
          + (f" at ≤ {a.max_price:,} T" if a.max_price else "") + f", every {a.interval}s. Ctrl+C to stop.")
    deadline = time.time() + a.duration if a.duration else None
    while True:
        try:
            p = fetch(pid)
            hits = [v for v in p.get("variants") or []
                    if in_stock(v) and matches(v, a.variant, a.exclude)
                    and (not a.max_price or v["price"]["selling_price"] // 10 <= a.max_price)]
            stamp = time.strftime("%H:%M:%S")
            if hits:
                best = min(hits, key=lambda v: v["price"]["selling_price"])
                msg = (f"{' / '.join(options(best))} - {toman(best['price']['selling_price'])} T "
                       f"({best['seller']['title']})")
                print(f"[{stamp}] AVAILABLE: {msg}\n  {url}")
                notify("Digikala: available!", msg, url)
                if sys.platform == "darwin":
                    subprocess.run(["open", url], check=False)
                return 0
            print(f"[{stamp}] not available yet")
            if a.once:
                return 1
        except KeyboardInterrupt:
            raise
        except Exception as e:  # network hiccups, rate limits: keep going
            print(f"[{time.strftime('%H:%M:%S')}] error: {e}")
            if a.once:
                return 2
        if deadline and time.time() + a.interval > deadline:
            return 1
        time.sleep(a.interval + random.randint(0, 5))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
