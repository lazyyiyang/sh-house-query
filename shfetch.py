#!/usr/bin/env python3
"""上海楼市 & 租房市场数据采集 —— 站统一 CLI。

数据源（均已实测可用）：
  1. 上海市住房租赁公共服务平台   POST /HouseInfo/getNewHouseInfo  → 租房挂牌房源 JSON
  2. 上海市统计局                  /sjxx/index.html                → 房地产开发月度数据（正文）
  3. 房天下                       loupan/{id}/chengjiao/          → 二手房成交记录（cookie 免滑块）
  4. 高德 Web 服务 API            restapi.amap.com                → 两点间距离+耗时

用法：
  python3 shfetch.py rent [--region 浦东] [--rtype 4] [--flat 2] [--maxpages N] [--out x.csv]
  python3 shfetch.py dev  [--months N] [--out x.csv]
  python3 shfetch.py deal --name 康定大楼 [--maxpage N] [--out x.csv]
  python3 shfetch.py geo --from 康定大楼 --to 人民广场 [--mode driving|bus|walking|riding] [--key XX]

字段说明：
  rtype: 1=经纪机构 2=代理经租 3=个人 4=长租公寓   flat: 1=一居 2=二居 3=三居 4=四居 5=五居
  geo 的 key 用 --key 传"""

import argparse
import csv
import datetime
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
RENT_API = "https://zfzl.fgj.sh.gov.cn/HouseInfo/getNewHouseInfo"
RENT_REF = "https://zfzl.fgj.sh.gov.cn/information/allHouseInfo.html"
STATS_LIST = "https://tjj.sh.gov.cn/sjxx/index.html"
RENT_FIELDS = [
    "regionname",
    "communityname",
    "communityAddress",
    "streetname",
    "flattypename",
    "area",
    "price",
    "renttypename",
    "houseresourcetypename",
    "fitment",
    "floorname",
    "checknum",
    "houseid",
]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "ignore")


def _post(url, data, referer):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": UA,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def _write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n已写入 {len(rows)} 条 → {path}")


# ---------------- 租房房源 ----------------
def fetch_rent(out, region, rtype, flat, rent, maxpages, delay):
    page, rows, total_pages = 1, [], None
    while True:
        data = {"pageno": page, "pageNo": page}
        if region:
            data["regionname"] = region
        if rtype:
            data["houseresourcetype"] = rtype
        if flat:
            data["flattype"] = flat
        if rent:
            data["renttypename"] = rent
        try:
            d = _post(RENT_API, data, RENT_REF)
        except Exception as e:
            sys.stderr.write(f"\n抓取失败(第{page}页): {e}\n")
            break
        if str(d.get("errorCode")) != "1":  # 接口 errorCode 为字符串 '1' 表示成功
            sys.stderr.write(f"接口返回错误: {d}\n")
            break
        info = d["dataInfo"]["info"]
        rows.extend(info)
        total_pages = d["dataInfo"]["page"]["totalPages"]
        sys.stderr.write(f"\r已抓 {page}/{total_pages} 页 · {len(rows)} 条")
        sys.stderr.flush()
        if page >= total_pages or (maxpages and page >= maxpages):
            break
        page += 1
        time.sleep(delay)
    _write_csv(out, rows, RENT_FIELDS)


# ---------------- 房地产开发月度数据 ----------------
DEV_METRICS = [
    "商品房施工面积",
    "住宅施工面积",
    "商品房新开工面积",
    "住宅新开工面积",
    "商品房竣工面积",
    "住宅竣工面积",
    "商品房销售面积",
    "住宅销售面积",
]


def _delta(s):
    """s 如 '增长2.4%' / '下降13.9%' / '与去年同期持平' → 带符号百分数"""
    s = s.strip("，。、 ")
    if "持平" in s:
        return 0.0
    m = re.search(r"(增长|下降)([\d.]+)%", s)
    if not m:
        return None
    return (1 if m.group(1) == "增长" else -1) * float(m.group(2))


def parse_dev(html, title):
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", "", text)
    m_period = re.search(r"(20\d{2}年\d+月|20\d{2}年1-\d+月)", title) or re.search(
        r"(20\d{2}年)", title
    )
    rec = {"period": m_period.group(1) if m_period else title}
    m = re.search(r"房地产开发投资比去年同期([^。]{0,12})", text)
    if m:
        rec["投资增速%"] = _delta(m.group(1))
    for name in DEV_METRICS:
        m = re.search(re.escape(name) + r"([\d.]+)万平方米，([^。]{0,12})", text)
        if m:
            rec[name + "_万㎡"] = float(m.group(1))
            rec[name + "_增速%"] = _delta(m.group(2))
    rec["原文"] = re.sub(r"\s+", " ", text)[:400]
    return rec


def _dev_links():
    page = 1
    while page <= 92:
        url = (
            STATS_LIST if page == 1 else f"https://tjj.sh.gov.cn/sjxx/index_{page}.html"
        )
        try:
            html = _get(url)
        except Exception:
            break
        yield from re.findall(
            r'href="(/sjxx/\d{8}/[a-f0-9]+\.html)"[^>]*title="([^"]*房地产开发[^"]*)"',
            html,
        )
        page += 1


def fetch_dev(out, months):
    rows = []
    for path, title in _dev_links():
        if months and len(rows) >= months:
            break
        try:
            page = _get("https://tjj.sh.gov.cn" + path)
            rows.append(parse_dev(page, title))
            print(f"✓ {rows[-1]['period']}")
        except Exception as e:
            print(f"✗ {title}: {e}")
    fields = (
        ["period", "投资增速%"]
        + [m for name in DEV_METRICS for m in (name + "_万㎡", name + "_增速%")]
        + ["原文"]
    )
    _write_csv(out, rows, fields)


# ---------------- 二手房成交（房天下，cookie 免滑块） ----------------
FANG_BASE = "https://sh.esf.fang.com"
FANG_SUGG = "/asynclist/searchsuggestion/suggestionList"
FANG_CJ_BASE = "/loupan/{id}/chengjiao/"


def _otherid():
    """房天下反爬 cookie：otherid=MD5('ETFio#dr'+YYYYMMDDHH+'lzkrZlt')，1 小时有效。"""
    now = datetime.datetime.now()
    p2 = lambda n: f"{n:02d}"
    s = f"ETFio#dr{now.year}{p2(now.month)}{p2(now.day)}{p2(now.hour)}lzkrZlt"
    return hashlib.md5(s.encode()).hexdigest()


def _fetch_fang(url, cookie):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Encoding": "gzip",
            "Cookie": f"otherid={cookie}",
            "Referer": FANG_BASE + "/chengjiao/",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read()
        return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def _resolve_fang_id(name, cookie):
    """按小区名查 loupan id。返回 (id, projname)。"""
    params = {"city": "上海", "q": name, "purpose": "住宅,别墅,商业,用户词,社区"}
    url = FANG_BASE + FANG_SUGG + "?" + urllib.parse.urlencode(params)
    body = _fetch_fang(url, cookie).decode("utf-8", "ignore")
    hits = re.findall(r"\"id\":\"(\d+)\",\"projname\":\"([^\"]+)\"", body)
    if not hits:
        return None, None
    for cid, pname in hits:  # 优先完全匹配
        if pname == name:
            return cid, pname
    return hits[0][0], hits[0][1]


def _parse_cj(html):
    """从成交表格提取 [(面积, 时间, 总价, 均价, 来源), ...]。"""
    table = re.search(r"房源面积.*?</table>", html, re.S)
    if not table:
        return []
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", table.group(0), re.S):
        cells = re.findall(r"<td><p>([^<]+)</p></td>", tr)
        if len(cells) >= 5 and "元/㎡" in cells[3]:
            rows.append(cells[:5])
    return rows


def _next_page_href(html):
    """找下一页链接 href（房天下用 #PageControl1_hlk_next），没有则 None。"""
    m = re.search(r'id="PageControl1_hlk_next"[^>]*href="([^"]+)"', html)
    if not m:
        m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*下一页\s*</a>', html)
    if not m:
        return None
    h = m.group(1)
    if h.startswith("//"):
        return "https:" + h
    if h.startswith("/"):
        return FANG_BASE + h
    return h


def fetch_deal(out, name, community, maxpage):
    cookie = _otherid()
    cid = community
    if name:
        cid, projname = _resolve_fang_id(name, cookie)
        if not cid:
            print(f"未找到小区: {name}")
            return
        print(f"小区「{name}」→ id {cid}（{projname}）")
    all_rows, seen = [], set()
    url = FANG_BASE + FANG_CJ_BASE.format(id=cid)
    page_no = 0
    while page_no < maxpage:
        page_no += 1
        try:
            html = _fetch_fang(url, cookie).decode("utf-8", "ignore")
        except Exception as e:
            print(f"第{page_no}页抓取出错: {e}")
            break
        rows = _parse_cj(html)
        if not rows:
            break
        new = [r for r in rows if tuple(r) not in seen]
        all_rows.extend(new)
        seen.update(map(tuple, new))
        print(f"第{page_no}页: 新增{len(new)}, 累计{len(all_rows)}")
        if not new:  # 无新记录，判定已到尾页
            break
        nxt = _next_page_href(html)
        if not nxt:
            break
        url = nxt
        time.sleep(0.3)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["面积", "成交时间", "成交总价", "成交均价", "来源"])
        w.writerows(all_rows)
    print(f"共 {len(all_rows)} 条 → {out}")


# ---------------- 两点距离/耗时（高德 Web 服务 API） ----------------
AMAP = "https://restapi.amap.com/v3"
GEO_MODES = {
    "driving": ("/direction/driving", "驾车"),
    "walking": ("/direction/walking", "步行"),
    "riding": ("/direction/bicycling", "骑行"),
}


def _amap(path, params, key):
    p = dict(params)
    p["key"] = key
    url = AMAP + path + "?" + urllib.parse.urlencode(p)
    req = urllib.request.Request(url, headers={"User-Agent": "sh-housing-geo"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _geocode(addr, key, city="上海"):
    d = _amap("/geocode/geo", {"address": addr, "city": city}, key)
    if d.get("status") != "1" or not d.get("geocodes"):
        raise ValueError(f"地理编码失败({addr}): {d.get('info')}")
    g = d["geocodes"][0]
    return g["location"], g.get("formatted_address")


def fetch_geo(fr, to, mode, key, city):
    if not key:
        print("缺少高德 Key：用 --key 或设环境变量 AMAP_KEY")
        return
    try:
        src, src_addr = _geocode(fr, key, city)
        dst, dst_addr = _geocode(to, key, city)
    except ValueError as e:
        print(e)
        return
    if mode == "bus":  # 公交响应结构不同
        d = _amap(
            "/direction/transit/integrated",
            {"origin": src, "destination": dst, "city": city, "strategy": "0"},
            key,
        )
        if d.get("status") == "1" and d.get("route", {}).get("transits"):
            t = d["route"]["transits"][0]
            dur = int(t["duration"])
            dist = int(t.get("distance", 0))
            print(
                f"公交: {dist / 1000:.1f} km, 预计 {dur // 3600}h{dur % 3600 // 60:02d}m | {src_addr} → {dst_addr}"
            )
        else:
            print("公交接口:", d.get("info", "未知错误"))
        return
    api, label = GEO_MODES.get(mode, GEO_MODES["driving"])
    d = _amap(api, {"origin": src, "destination": dst, "extensions": "base"}, key)
    if d.get("status") == "1" and d.get("route", {}).get("paths"):
        p = d["route"]["paths"][0]
        dist = int(p["distance"])
        dur = int(p["duration"])
        print(
            f"{label}: {dist / 1000:.2f} km, 预计 {dur // 60} 分 {dur % 60} 秒 | {src_addr} → {dst_addr}"
        )
    else:
        print(f"{label}接口:", d.get("info", "未知错误"))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rent", help="租房挂牌房源（租赁平台 API）")
    r.add_argument("--region", help="区，如 浦东/徐汇")
    r.add_argument("--rtype", help="房源类型 1/2/3/4")
    r.add_argument("--flat", help="户型 1-5")
    r.add_argument("--rent", help="出租方式，如 整租")
    r.add_argument("--maxpages", type=int, help="最多抓取页数")
    r.add_argument("--delay", type=float, default=0.15)
    r.add_argument("--out", default="data/rent.csv")
    d = sub.add_parser("dev", help="房地产开发月度数据（统计局）")
    d.add_argument("--months", type=int, help="抓取最近 N 个月")
    d.add_argument("--out", default="data/dev.csv")
    dl = sub.add_parser("deal", help="二手房成交记录（房天下）")
    dl.add_argument("--name", help="小区名，如 康定大楼（自动解析 id）")
    dl.add_argument("--community", help="房天下小区 id")
    dl.add_argument("--maxpage", type=int, default=20)
    dl.add_argument("--out", default="data/chengjiao.csv")
    g = sub.add_parser("geo", help="两点间距离+耗时（高德 Web 服务）")
    g.add_argument("--from", dest="fr", required=True, help="起点地址/小区名")
    g.add_argument("--to", required=True, help="终点地址")
    g.add_argument(
        "--mode", default="driving", choices=["driving", "bus", "walking", "riding"]
    )
    g.add_argument("--city", default="上海")
    g.add_argument("--key", help="高德 Web 服务 Key（或设环境变量 AMAP_KEY）")
    a = ap.parse_args()
    if a.cmd == "rent":
        fetch_rent(a.out, a.region, a.rtype, a.flat, a.rent, a.maxpages, a.delay)
    elif a.cmd == "dev":
        fetch_dev(a.out, a.months)
    elif a.cmd == "deal":
        fetch_deal(a.out, a.name, a.community, a.maxpage)
    else:
        fetch_geo(a.fr, a.to, a.mode, a.key or os.environ.get("AMAP_KEY", ""), a.city)


if __name__ == "__main__":
    main()
