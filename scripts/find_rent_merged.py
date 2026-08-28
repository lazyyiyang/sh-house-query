#!/usr/bin/env python3
"""房源全量合并：房天下租房 + 太平洋房屋租房，取并集，按小区合并去重，筛达标。

筛选：长宁+静安，7000-13000元/月，电梯房>2000年，到金钟路968号<40分，地铁<10分。
地铁距离优先用太平洋官方 nearMetroStationDistance，否则用房天下卡片「距X站X米」，兜底高德。
用法：python3 find_rent_merged.py
输出：data/rent_merged.csv
"""

import csv
import os
import re
import sys
import time

import find_homes as f

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA, exist_ok=True)
LO, HI = 7000, 13000
AREAS = [3, 4]
UA = f.UA


def fang_pull():
    """房天下租房卡片（长宁+静安, 7000-13000），带小区名/价格/面积/户型/卡片地铁距离。"""
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
            new = fang_parse(html)
            cards.extend(new)
            if "下一页" not in html or not new or page > 15:
                break
            time.sleep(0.15)
    return cards


def fang_parse(html):
    out = []
    for c in re.split(r'<dl class="list hiddenMap rel "', html)[1:]:
        mn = re.search(r'house-xm\d+/" target="_blank"><span>([^<]+)</span>', c)
        mp = re.search(r'<span class="price">(\d+)</span>', c)
        ma = re.search(r"([\d.]+)㎡", c)
        mr = re.search(r"(\d)室(\d)厅", c)
        mm = re.search(r"距(.+?站)约([\d.]+)米", c)
        if mn and mp:
            out.append(
                {
                    "estateName": mn.group(1),
                    "rentPrice": int(mp.group(1)),
                    "propertySquare": float(ma.group(1)) if ma else 0,
                    "rooms": f"{mr.group(1)}室{mr.group(2)}厅" if mr else "",
                    "metro": float(mm.group(2)) if mm else None,
                    "src": "房天下",
                }
            )
    return out


def main():
    print("1) 拉太平洋房屋 + 房天下 租房...")
    tw = f.taiwu_pull(ptype=2, areas=AREAS, price_lo=LO, price_hi=HI)
    fg = fang_pull()
    print(f"   太平洋 {len(tw)} 条 | 房天下 {len(fg)} 条")

    xq = f.enumerate_xiaoqu()
    xq_by_name = {c["name"]: c for c in xq}
    print(f"2) 小区库 {len(xq)}")

    from collections import defaultdict

    by_comm = defaultdict(list)
    for x in tw:
        if x.get("areaName") not in ("长宁", "静安"):
            continue
        by_comm[x["estateName"]].append(
            {
                "src": "太平洋",
                "rentPrice": x.get("rentPrice"),
                "square": x.get("propertySquare"),
                "rooms": f"{x.get('roomNum')}室{x.get('hallNum')}厅",
                "metro": x.get("nearMetroStationDistance"),
                "year": x.get("createYear"),
                "totalLayer": x.get("totalLayer"),
            }
        )
    for x in fg:
        c = xq_by_name.get(x["estateName"])
        if not c:
            continue
        by_comm[x["estateName"]].append(
            {
                "src": "房天下",
                "rentPrice": x["rentPrice"],
                "square": x["propertySquare"],
                "rooms": x["rooms"],
                "metro": x["metro"],
                "year": c.get("year"),
                "totalLayer": None,
            }
        )
    print(f"3) 小区数 {len(by_comm)}")

    tg = tuple(
        map(
            float,
            f._amap("/geocode/geo", {"address": f.TARGET, "city": "上海"})["geocodes"][
                0
            ]["location"].split(","),
        )
    )
    stations = f.get_metro_stations()
    print(f"   金钟路968号 {tg}, 地铁站{len(stations)}")

    results = []
    for i, (ename, rents) in enumerate(by_comm.items()):
        c = xq_by_name.get(ename)
        coord = f.resolve_coord(ename) if c else None
        if not coord:
            continue
        year = next((r["year"] for r in rents if r.get("year")), None)
        if not year or not str(year)[:4].isdigit() or int(str(year)[:4]) < 2001:
            continue
        tls = [r.get("totalLayer") for r in rents if r.get("totalLayer")]
        if tls:
            if max(tls) < 7:
                continue
            tl = max(tls)
        else:
            cid = c.get("id") if c else None
            if not cid:
                continue
            fc = f.floor_count(cid)
            if not fc or fc < 7:
                continue
            tl = fc
        km = round(f.euclid(coord, tg), 2)
        if km >= 8:
            continue
        drive = f.amap_drive(coord, tg)
        if not drive or drive[1] >= 40:
            continue
        metro = min([r["metro"] for r in rents if r.get("metro")] or [999999])
        if metro >= 999999:
            best = min(
                ((f.euclid(coord, p), n, p) for n, p in stations.items()),
                key=lambda x: x[0],
            )
            walk = f.amap_walk_to_station(coord, best[2])
            ok_metro = walk is not None and walk < 10
            metro_label = f"高德{walk:.0f}分" if walk is not None else "?"
        else:
            ok_metro = metro <= 600
            metro_label = f"{metro:.0f}m"
        results.append(
            {
                "OK": "✓" if ok_metro else "",
                "name": ename,
                "year": year,
                "totalLayer": tl,
                "km": km,
                "drive": f"{drive[0]:.1f}km/{drive[1]:.0f}分",
                "metro": metro_label,
                "n": len(rents),
                "listings": " | ".join(
                    f"[{r['src']}]{r['rooms']}{r['square']}㎡{r['rentPrice']}元"
                    for r in rents[:3]
                ),
            }
        )
        if i % 8 == 0:
            sys.stderr.write(f"   处理 {i}/{len(by_comm)}\n")
        time.sleep(0.2)

    results.sort(key=lambda r: (not r["OK"], r["km"]))
    with open(
        os.path.join(DATA, "rent_merged.csv"), "w", newline="", encoding="utf-8-sig"
    ) as fp:
        w = csv.DictWriter(
            fp,
            fieldnames=[
                "OK",
                "name",
                "year",
                "totalLayer",
                "km",
                "drive",
                "metro",
                "n",
                "listings",
            ],
        )
        w.writeheader()
        w.writerows(results)
    print(f"\n共 {len(results)} 小区写入 data/rent_merged.csv")
    for r in results:
        if r["OK"]:
            print(
                f"✓ {r['name']} {r['year']}年 {r['totalLayer']}层 金钟路{r['drive']} 地铁{r['metro']} 房源{r['n']}套 | {r['listings']}"
            )


if __name__ == "__main__":
    main()
