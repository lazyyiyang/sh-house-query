#!/usr/bin/env python3
"""房天下租房版筛选：长宁+静安，7000-13000元/月，电梯房>2000年，到金钟路968号<40分，地铁步行<10分。

租房卡片源自带「距X号线XX站约X米」，作为地铁预筛；电梯层数取在售房源详情。
复用 find_homes 的小区枚举/坐标/高德助手。
用法：python3 find_rent_fang.py
输出：data/rent_fang_result.csv
"""

import csv
import os
import re
import sys
import time

import find_homes as f

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA, exist_ok=True)
LO, HI = 7000, 13000
ROOMS = {"1": "一居", "2": "二居", "3": "三居", "4": "四居"}


def crawl_rent():
    """抓长宁+静安 7000-13000 租房卡片。"""
    cards = []
    lo, hi = f"2{LO}", f"2{HI}"
    for code in ["a020", "a021"]:
        page = 0
        while True:
            page += 1
            base = f"https://sh.zu.fang.com/house-{code}/c{lo}-d{hi}"
            url = base + ("/" if page == 1 else f"-i3{page}/")
            try:
                html = f._fang(url).decode("utf-8", "ignore")
            except Exception:
                break
            new = parse_cards(html)
            cards.extend(new)
            if "下一页" not in html or not new or page > 15:
                break
            time.sleep(0.15)
    return cards


def parse_cards(html):
    out = []
    for c in re.split(r'<dl class="list hiddenMap rel "', html)[1:]:
        mid = re.search(r"house-xm(\d+)/", c)
        mname = re.search(r'house-xm\d+/" target="_blank"><span>([^<]+)</span>', c)
        mprice = re.search(r'<span class="price">(\d+)</span>', c)
        marea = re.search(r"([\d.]+)㎡", c)
        mrooms = re.search(r"(\d)室(\d)厅", c)
        mmet = re.search(r"距(.+?站)约([\d.]+)米", c)
        mregion = re.search(r"house-a0\d+.*?<span>([^<]+)</span>", c)
        if mid and mprice:
            out.append(
                {
                    "cid": mid.group(1),
                    "name": mname.group(1) if mname else "",
                    "price": int(mprice.group(1)),
                    "area": float(marea.group(1)) if marea else 0,
                    "rooms": (mrooms.group(1) + "室" + mrooms.group(2) + "厅")
                    if mrooms
                    else "",
                    "metro": (mmet.group(1), float(mmet.group(2))) if mmet else None,
                }
            )
    return out


def main():
    print("1) 抓长宁+静安 7000-13000 租房...")
    cards = crawl_rent()
    print(f"   → {len(cards)} 条租房")
    print("2) 枚举长宁+静安小区...")
    xq = f.enumerate_xiaoqu()
    bynm = {c["name"]: c for c in xq}
    byid = {c["id"]: c for c in xq}
    print(f"   → {len(xq)} 小区")

    d = f._amap("/geocode/geo", {"address": f.TARGET, "city": "上海"})
    tg = tuple(map(float, d["geocodes"][0]["location"].split(",")))
    stations = f.get_metro_stations()
    print(f"   目标{tg}, 地铁站{len(stations)}")

    # 聚合到小区
    from collections import defaultdict

    agg = defaultdict(list)
    for c in cards:
        agg[c["name"]].append(c)
    # 候选小区
    cand = []
    for cname, cs in agg.items():
        x = bynm.get(cname) or (
            next((v for k, v in bynm.items() if k in cname or cname in k), None)
        )
        if not x:
            continue
        if x["year"] < 2001 or x["type"] not in ("住宅", "公寓"):
            continue
        x["coord"] = f.resolve_coord(cname)
        if not x["coord"]:
            continue
        # 该小区 7000-13000 房源（含地铁距离的）
        rents = [c for c in cs if LO <= c["price"] <= HI]
        x["rents"] = rents
        x["km"] = round(f.euclid(x["coord"], tg), 2)
        mds = [c["metro"][1] for c in cs if c.get("metro") and c["metro"][1]]
        x["metro_m"] = min(mds) if mds else 999999
        cand.append(x)
    near = [c for c in cand if c["km"] < 8 and c["metro_m"] < 600]
    print(
        f"3) 建成>2000+住宅/公寓+有坐标: {len(cand)} | 预筛(金钟路<8km&地铁<600m): {len(near)}"
    )

    print("4) 高德确认+电梯...")
    results = []
    for i, c in enumerate(near):
        drive = f.amap_drive(c["coord"], tg)
        floors = f.floor_count(c["id"])
        ok = drive and drive[1] < 40 and c["metro_m"] <= 600 and floors and floors >= 7
        results.append(
            {
                "name": c["name"],
                "district": c["district"],
                "year": c["year"],
                "floors": floors,
                "km": c["km"],
                "drive": f"{drive[0]:.1f}km/{drive[1]:.0f}分" if drive else "-",
                "station": "-",
                "walk": f"{c['metro_m']:.0f}m" if c["metro_m"] < 999999 else "-",
                "rent_n": len(c["rents"]),
                "OK": "✓" if ok else "",
            }
        )
        if i % 8 == 0:
            sys.stderr.write(f"   高德 {i}/{len(near)}\n")
        time.sleep(0.3)

    results.sort(key=lambda r: (not r["OK"], r["km"]))
    with open(
        os.path.join(DATA, "rent_fang_result.csv"),
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as fp:
        w = csv.DictWriter(
            fp,
            fieldnames=[
                "OK",
                "name",
                "district",
                "year",
                "floors",
                "km",
                "drive",
                "station",
                "walk",
                "rent_n",
            ],
        )
        w.writeheader()
        w.writerows(results)
    print(f"\n共 {len(results)} 小区写入 data/rent_fang_result.csv")
    # 打印达标小区的具体房源
    for r in results:
        if r["OK"]:
            x = next((c for c in near if c["name"] == r["name"]), None)
            print(
                f"\n✓ {r['name']} {r['year']}年 {r['floors']}层 金钟路{r['drive']} 地铁{r['station']}步{r['walk']}"
            )
            if x:
                for rent in x["rents"]:
                    print(
                        f"      {rent['rooms']:6s} {rent['area']:>6.1f}㎡ {rent['price']:>6}元/月 距{rent['metro'][0]}约{rent['metro'][1]:.0f}米"
                        if rent["metro"]
                        else f"      {rent['rooms']:6s} {rent['area']:>6.1f}㎡ {rent['price']:>6}元/月"
                    )


if __name__ == "__main__":
    main()
