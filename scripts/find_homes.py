#!/usr/bin/env python3
"""上海选房全链路筛查：长宁+静安，电梯房>2000年，到金钟路968号<40分，地铁<10分，500-800万。

数据源：
  - 房天下小区目录（cookie）→ 小区列表（建成年份/均价/类型/坐标）
  - 房天下小区详情 → 总层数(判断电梯)
  - 高德 → 地铁站(一次性)、驾车通勤、地铁步行、地理编码
用法：
  python3 find_homes.py 2>/dev/null
输出：data/result.csv（按地铁步行升序）
"""

import csv
import datetime
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA, exist_ok=True)


def get_key():
    """高德 Key 从环境变量读取，缺失即报错（不再硬编码）。"""
    k = os.environ.get("AMAP_KEY")
    if not k:
        raise SystemExit(
            "缺少 AMAP_KEY：请设置环境变量后重跑\n  AMAP_KEY=你的key python3 find_homes.py"
        )
    return k


DISTRICTS = {"长宁": "20__0_3_0_0_{p}_0_0_0", "静安": "21__0_3_0_0_{p}_0_0_0"}
TARGET = "金钟路968号"


# ---------------- 基础请求 ----------------
def _otherid():
    now = datetime.datetime.now()
    p2 = lambda n: f"{n:02d}"
    return hashlib.md5(
        f"ETFio#dr{now.year}{p2(now.month)}{p2(now.day)}{p2(now.hour)}lzkrZlt".encode()
    ).hexdigest()


def _fang(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Encoding": "gzip",
            "Cookie": f"otherid={_otherid()}",
            "Referer": "https://sh.esf.fang.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        d = r.read()
        return gzip.decompress(d) if d[:2] == b"\x1f\x8b" else d


def _amap(path, params):
    p = dict(params)
    p["key"] = get_key()
    url = "https://restapi.amap.com/v3" + path + "?" + urllib.parse.urlencode(p)
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "find-homes"}), timeout=15
    ) as r:
        return json.loads(r.read().decode())


# ---------------- 太平洋房屋 API（共享，免鉴权） ----------------
TAIWU_API = "https://taiwuapigateway.taiwu.com/user/api/v1/properties/pageList"


def taiwu_call(area, page, ptype, price_lo=None, price_hi=None):
    """太平洋房屋分页查询。price_lo/hi 为万；property_type: 1=二手房, 2=租房。"""
    if ptype == 1:
        ps, pe, rps, rpe = str(price_lo or ""), str(price_hi or ""), "", ""
    else:
        ps, pe, rps, rpe = "", "", str(price_lo or ""), str(price_hi or "")
    body = {
        "propertyType": ptype,
        "areaId": area,
        "plateIdList": [],
        "metroLineId": None,
        "metroStationIdList": [],
        "loopCode": [],
        "priceStart": ps,
        "priceEnd": pe,
        "priceCode": [],
        "rentPriceStart": rps,
        "rentPriceEnd": rpe,
        "rentPriceCode": [],
        "rentModeCode": [],
        "squareStart": "",
        "squareEnd": "",
        "squareCode": [],
        "roomNumCode": [],
        "buildingDirectionCode": [],
        "layerHighLowCode": [],
        "buildingAgeCode": [],
        "elevatorExists": [],
        "label": [],
        "buildingAgeStart": "",
        "buildingAgeEnd": "",
        "decorationCode": [],
        "houseFullYear": [],
        "haveVrFlg": None,
        "nearMetroFlg": None,
        "nearSchoolFlg": None,
        "takeLookTimeCode": None,
        "houseKeyFlg": None,
        "houseLabel": None,
        "pageNum": page,
        "pageSize": 20,
    }
    req = urllib.request.Request(
        TAIWU_API,
        data=json.dumps(body).encode(),
        headers={
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Referer": "https://www.taiwu.com",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        d = r.read()
        return json.loads(gzip.decompress(d) if d[:2] == b"\x1f\x8b" else d)["data"]


def taiwu_pull(ptype, areas, price_lo=None, price_hi=None):
    """拉取指定区、价格段的全部房源（自动分页）。"""
    out = []
    for area in areas:
        page = 1
        while page <= 60:
            d = taiwu_call(area, page, ptype, price_lo, price_hi)
            pl = d.get("pageList") or []
            out.extend(pl)
            if page >= d.get("totalPage", 1):
                break
            page += 1
            time.sleep(0.15)
    return out


# ---------------- 1) 枚举小区（修好的分页，带磁盘缓存） ----------------
def enumerate_xiaoqu(cache=True):
    fp = os.path.join(DATA, "xiaoqu_all.json")
    if cache and os.path.exists(fp):
        return json.load(open(fp))
    seen = {}
    for dname, urlt in DISTRICTS.items():
        page, empty = 1, 0
        while page <= 100:
            url = f"https://sh.esf.fang.com/housing/{urlt.format(p=page)}/"
            try:
                html = _fang(url).decode("utf-8", "ignore")
            except Exception:
                break
            rows = parse_cards(html, dname)
            if not rows:
                empty += 1
                if empty >= 2:
                    break
            for r in rows:
                seen[r["id"]] = r
            if "末页" not in html:
                break
            page += 1
            time.sleep(0.1)
            if page % 10 == 0:
                sys.stderr.write(f"[{dname}] 已抓 {page} 页, {len(seen)} 小区\n")
    out = list(seen.values())
    json.dump(out, open(fp, "w"), ensure_ascii=False)
    return out


def parse_cards(html, dname):
    rows = []
    for c in re.split(r'class="plotListwrap clearfix"', html)[1:]:
        mid = re.search(r"/loupan/(\d+)\.htm", c)
        mname = re.search(r'class="plotTit">([^<]+)</a>', c)
        mtype = re.search(r'class="plotFangType">([^<]*)</span>', c)
        myear = re.search(r"(\d{4})年建成", c)
        mprice = re.search(r'class="priceAverage"><span>\s*(\d+)\s*</span>', c)
        msale = re.search(r"(\d+)\s*</a>套在售", c)
        if mid and mname:
            rows.append(
                {
                    "id": mid.group(1),
                    "name": mname.group(1),
                    "district": dname,
                    "type": mtype.group(1) if mtype else "",
                    "year": int(myear.group(1)) if myear else 0,
                    "price": int(mprice.group(1)) if mprice else 0,
                    "sales": int(msale.group(1)) if msale else 0,
                }
            )
    return rows


# ---------------- 2) 坐标 + 电梯(总层数) ----------------
def resolve_coord(name):
    u = (
        "https://sh.esf.fang.com/asynclist/searchsuggestion/suggestionList?"
        + urllib.parse.urlencode(
            {"city": "上海", "q": name, "purpose": "住宅,别墅,商业,用户词,社区"}
        )
    )
    try:
        b = _fang(u).decode("utf-8", "ignore")
        hits = re.findall(
            r'"id":"(\d+)","projname":"([^"]+)"[^}]*?"coordx":"([\d.]+)","coordy":"([\d.]+)"',
            b,
        )
        for cid, pn, x, y in hits:
            if pn == name:
                return (float(x), float(y))
        return (float(hits[0][2]), float(hits[0][3])) if hits else None
    except Exception:
        return None


def floor_count(cid):
    """从小区的在售房源详情页取 总层数(共X层) 判断电梯。"""
    try:
        html = _fang(f"https://sh.esf.fang.com/loupan/{cid}/chushou/").decode(
            "utf-8", "ignore"
        )
        m = re.search(r"/chushou/3_\d+\.htm", html)
        if not m:
            return None
        detail = _fang("https://sh.esf.fang.com" + m.group(0)).decode("utf-8", "ignore")
        m2 = re.search(r"共(\d+)层|(\d+)/(\d+)层", detail)
        return int(m2.group(1) or m2.group(3)) if m2 else None
    except Exception:
        return None


# ---------------- 3) 地铁站(一次性缓存) ----------------
def get_metro_stations():
    fp = os.path.join(DATA, "metro.json")
    if os.path.exists(fp):
        return json.load(open(fp))
    stations = {}
    for page in range(1, 40):
        d = _amap(
            "/place/text",
            {
                "keywords": "地铁站",
                "city": "上海",
                "offset": 25,
                "page": page,
                "extensions": "base",
            },
        )
        if d.get("status") != "1":
            break
        pois = d.get("pois", [])
        if not pois:
            break
        for p in pois:
            xy = p["location"].split(",")
            stations[p["name"]] = (float(xy[0]), float(xy[1]))
        time.sleep(0.2)
    json.dump(stations, open(fp, "w"), ensure_ascii=False)
    return stations


# ---------------- 4) 几何/高德 ----------------
def euclid(a, b):
    if not a or not b:
        return 1e9
    dx = (a[0] - b[0]) * 111.32 * math.cos(math.radians(31.22))
    dy = (a[1] - b[1]) * 110.57
    return math.hypot(dx, dy)


def amap_drive(a, b):
    d = _amap(
        "/direction/driving",
        {
            "origin": f"{a[0]},{a[1]}",
            "destination": f"{b[0]},{b[1]}",
            "extensions": "base",
        },
    )
    if d.get("status") == "1" and d.get("route", {}).get("paths"):
        p = d["route"]["paths"][0]
        return int(p["distance"]) / 1000, int(p["duration"]) / 60
    return None


def amap_walk_to_station(a, station):
    d = _amap(
        "/direction/walking",
        {"origin": f"{a[0]},{a[1]}", "destination": f"{station[0]},{station[1]}"},
    )
    if d.get("status") == "1" and d.get("route", {}).get("paths"):
        return int(d["route"]["paths"][0]["duration"]) / 60
    return None


def in_sale_units(cid, lo=500, hi=800):
    """小区在售房源中 500-800万 的数量。"""
    try:
        html = _fang(f"https://sh.esf.fang.com/loupan/{cid}/chushou/").decode(
            "utf-8", "ignore"
        )
        m = re.search(r'class="shop_list"(.{0,60000})', html, re.S)
        seg = m.group(1) if m else html
        n = 0
        for c in re.split(r'<dl class="clearfix" dataflag="bg"', seg)[1:]:
            price = re.search(r"<b>(\d+)</b>万", c)
            area = re.search(r"建筑面积([\d.]+)㎡", c)
            if price and area and lo <= int(price.group(1)) <= hi:
                n += 1
        return n
    except Exception:
        return 0


# ---------------- 主流程 ----------------
def main():
    print("1) 枚举小区...")
    xq = enumerate_xiaoqu()
    print(f"   → {len(xq)} 个小区")
    # 过滤: 建成>2000 + 住宅/公寓
    cand = [
        c
        for c in xq
        if c["year"] >= 2001 and c["type"] in ("住宅", "公寓", "商住", "酒店式公寓")
    ]
    print(f"2) 建成>2000 且住宅/公寓: {len(cand)}")
    # 坐标
    with_xy = []
    for i, c in enumerate(cand):
        c["coord"] = resolve_coord(c["name"])
        if c["coord"]:
            c["km"] = round(euclid(c["coord"], None) if False else 0, 2)
            with_xy.append(c)
        if i % 20 == 0:
            sys.stderr.write(f"   坐标 {i}/{len(cand)}\n")
        time.sleep(0.05)
    print(f"3) 有坐标: {len(with_xy)}")
    # 距金钟路968号 直线距离
    tg = None
    d = _amap("/geocode/geo", {"address": TARGET, "city": "上海"})
    if d.get("status") == "1" and d.get("geocodes"):
        xy = d["geocodes"][0]["location"].split(",")
        tg = (float(xy[0]), float(xy[1]))
    print(f"   金钟路968号: {tg}")
    for c in with_xy:
        c["km"] = round(euclid(c["coord"], tg), 2)
    # 地铁站
    print("4) 获取地铁站(一次性)...")
    stations = get_metro_stations()
    print(f"   → {len(stations)} 站")
    # 预筛: 距金钟路<8km & 距任一地铁站直线<600m
    for c in with_xy:
        city_idx = [s for s, p in stations.items() if euclid(c["coord"], p) < 0.6]
        c["metro_straight"] = (
            min((euclid(c["coord"], p), s) for s, p in stations.items())[1]
            if stations
            else ""
        )
        c["metro_m"] = (
            round(min(euclid(c["coord"], p) for p in stations.values()) * 1000, 0)
            if stations
            else 1e9
        )
        c["near_station"] = (
            min((euclid(c["coord"], p), name) for name, p in stations.items())[1]
            if stations
            else ""
        )
    near = [c for c in with_xy if c["km"] < 8 and c["metro_m"] < 600]
    print(f"5) 预筛(距金钟路<8km & 地铁直线<600m): {len(near)}")
    # 高德确认: 驾车金钟路 + 地铁步行 + 在售房源 + 电梯
    results = []
    for i, c in enumerate(near):
        drive = amap_drive(c["coord"], tg)
        _, st_name = c["near_station"], None
        # 最近站坐标
        stp = min(
            ((p, n) for n, p in stations.items()),
            key=lambda x: euclid(c["coord"], x[0]),
        )
        stp = stp[0]
        # 用直线最近的那站走步行
        best = min(
            ((euclid(c["coord"], p), n, p) for n, p in stations.items()),
            key=lambda x: x[0],
        )
        walk = amap_walk_to_station(c["coord"], best[2])
        floors = floor_count(c["id"])
        sales = in_sale_units(c["id"])
        ok = (
            drive
            and drive[1] < 40
            and walk is not None
            and walk < 10
            and floors
            and floors >= 7
            and sales > 0
        )
        results.append(
            {
                "name": c["name"],
                "district": c["district"],
                "year": c["year"],
                "price": c["price"],
                "floors": floors,
                "km": c["km"],
                "drive": f"{drive[0]:.1f}km/{drive[1]:.0f}分" if drive else "-",
                "station": best[1],
                "walk": f"{walk:.0f}分" if walk is not None else "-",
                "sale500_800": sales,
                "OK": "✓" if ok else "",
            }
        )
        if i % 8 == 0:
            sys.stderr.write(f"   高德 {i}/{len(near)}\n")
        time.sleep(0.3)
    # 输出
    results.sort(key=lambda r: (not r["OK"], r["walk"] == "-" and 1 or 0, r["km"]))
    with open(
        os.path.join(DATA, "result.csv"), "w", newline="", encoding="utf-8-sig"
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "OK",
                "name",
                "district",
                "year",
                "price",
                "floors",
                "km",
                "drive",
                "station",
                "walk",
                "sale500_800",
            ],
        )
        w.writeheader()
        w.writerows(results)
    print(f"\n共 {len(results)} 候选写入 data/result.csv")
    for r in results:
        if r["OK"]:
            print(r)


if __name__ == "__main__":
    main()
