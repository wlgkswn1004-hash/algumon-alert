import json, os, re, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0"}
DB = "deals.json"
BOARDS = ["ppomppu", "ppomppu8"]  # 뽐뿌게시판, 알리뽐뿌
TV = re.compile(r"스탠바이미|티비|텔레비전|tv|oled|qled", re.I)
MAX_MSGS = int(os.environ.get("MAX_MSGS", 20))  # 과다 발송 방지


def req(url, data=None, headers=None):
    if data is not None:
        data = urllib.parse.urlencode(data).encode()
    r = urllib.request.Request(url, data, headers or UA)
    return urllib.request.urlopen(r, timeout=30).read().decode()


def fetch():
    out = {}
    for board in BOARDS:
        root = ET.fromstring(req(f"https://www.ppomppu.co.kr/rss.php?id={board}"))
        for it in root.iter("item"):
            link = it.findtext("link").replace("http://", "https://")
            created = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).isoformat()
            out[board + link.rsplit("=", 1)[1]] = {"t": it.findtext("title").strip(), "u": link, "c": created}
    assert out, "no deals parsed"
    return out


def collect():
    db = json.load(open(DB, encoding="utf8")) if os.path.exists(DB) else {}
    db.update(fetch())
    old = (datetime.now(KST) - timedelta(hours=48)).isoformat()
    db = {k: v for k, v in db.items() if v["c"] >= old}
    json.dump(db, open(DB, "w", encoding="utf8"), ensure_ascii=False, indent=0, sort_keys=True)
    print(f"{len(db)} deals stored")


def window(now):
    if os.environ.get("WINDOW_HOURS"):  # 테스트용: 최근 N시간
        return now - timedelta(hours=float(os.environ["WINDOW_HOURS"])), now
    b = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = max(c for c in (b - timedelta(hours=3), b + timedelta(hours=9), b + timedelta(hours=21)) if c <= now)
    return end - timedelta(hours=12), end


def chunks(lines, head):
    out, cur = [], head
    for l in lines:
        if len(cur) + len(l) + 1 > 3800 and cur != head:  # 텔레그램 4096자 제한
            out.append(cur)
            cur = head
        cur += "\n" + l
    return out + ([cur] if cur != head else [])


def build():
    db = json.load(open(DB, encoding="utf8"))
    start, end = window(datetime.now(KST))
    rows = [(k, v) for k, v in db.items() if start.isoformat() <= v["c"] < end.isoformat()]
    rows.sort(key=lambda r: r[1]["c"], reverse=True)
    n = 0

    def line(k, v):
        nonlocal n
        n += 1
        return f"{n}.{v['t'][:60]}-{v['u']}"

    tv = [line(k, v) for k, v in rows if TV.search(v["t"])]
    rest = [line(k, v) for k, v in rows if not TV.search(v["t"])]
    msgs = chunks(tv, "📺TV 특가!") + chunks(rest, f"🔥핫딜 {start:%H}~{end:%H}시")
    if len(msgs) > MAX_MSGS:
        msgs = msgs[:MAX_MSGS] + [f"(이후 {len(msgs) - MAX_MSGS}통 분량 생략)"]
    return msgs or [f"핫딜 {start:%H}~{end:%H}시: 새 딜 없음"]


def send(msgs):
    for m in msgs:
        print(req(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
                  {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": m, "disable_web_page_preview": "true"}))


if __name__ == "__main__":
    if sys.argv[1] == "collect":
        collect()
    elif os.environ.get("DRY_RUN"):
        print("\n---\n".join(build()))
    else:
        send(build())
