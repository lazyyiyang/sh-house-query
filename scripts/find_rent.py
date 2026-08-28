#!/usr/bin/env python3
"""上海租房筛查：长宁+静安，7000-13000元/月，电梯房>2000年，到金钟路968号<40分，地铁步行<10分。

复用 find_homes 的小区枚举/坐标/高德助手。
用法：python3 find_rent.py
输出：data/rent_result.csv
"""

import csv
import os
import sys
import time
import urllib.parse
import urllib.request

import find_homes as f

RENT_API = "https://zfzl.fgj.sh.gov.cn/HouseInfo/getNewHouseInfo"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA, exist_ok=True)
LO, HI = 7000, 13000


def rent_query(region, lo, hi, page=1):
    body = urllib.parse.urlencode(
        {
            "pageno": page,
            "pageNo": page,
            "regionname": region,
            "priceleast": lo,
            "pricemax": hi,
        }
    ).encode()
    req = urllib.request.Request(
        RENT_API,
        data=body,
        headers={
            "User-Agent": UA,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://zfzl.fgj.sh.gov.cn/information/allHouseInfo.html",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return __import__("json").loads(r.read().decode())


def pull_rent():
    listings = []
    for region in ["长宁", "静安"]:
        page, total = 1, None
        while True:
            d = rent_query(region, LO, HI, page)
            if d.get("errorCode") != "1":
                break
            info = d["dataInfo"]["info"]
            total = d["dataInfo"]["page"]["total"]
            listings.extend(info)
            if page * 10 >= total:
                break
            page += 1
            time.sleep(0.15)
    return listings


def main():
    print("1) 拉取租赁房源(长宁+静安, 7000-13000)...")
    listings = pull_rent()
    print(f"   → {len(listings)} 条房源")

    print("2) 枚举长宁+静安小区(房天下)...")
    xq = f.enumerate_xiaoqu()
    lookup = {c["name"]: c for c in xq}
    print(f"   → {len(lookup)} 小区")

    # 按小区聚合房源
    from collections import defaultdict

    by_comm = defaultdict(list)
    for l in listings:
        by_comm[l.get("communityname", "")].append(l)

    print("3) 过滤: 建成>2000 + 住宅/公寓 + 有坐标...")
    # 金钟路968号
    d = f._amap("/geocode/geo", {"address": f.TARGET, "city": "上海"})
    tg_xy = d["geocodes"][0]["location"].split(",")
    tg = (float(tg_xy[0]), float(tg_xy[1]))
    stations = f.get_metro_stations()
    print(f"   目标{tg}, 地铁站{len(stations)}个")

    cand = []
    for cname, ls in by_comm.items():
        c = lookup.get(cname)
        if not c:
            continue
        if c["year"] < 2001 or c["type"] not in ("住宅", "公寓"):
            continue
        c["coord"] = f.resolve_coord(cname)
        if not c["coord"]:
            continue
        c["rent_total"] = len(ls)
        c["rent_n"] = len([x for x in ls if LO <= int(x["price"]) <= HI])
        c["km"] = round(f.euclid(c["coord"], tg), 2)
        c["metro_m"] = round(
            min(f.euclid(c["coord"], p) for p in stations.values()) * 1000, 0
        )
        cand.append(c)
    # 预筛: 距金钟路<8km & 地铁直线<600m
    near = [c for c in cand if c["km"] < 8 and c["metro_m"] < 600]
    print(
        f"4) 建成>2000+住宅/公寓+有坐标: {len(cand)} | 预筛(金钟路<8km&地铁<600m): {len(near)}"
    )

    print("5) 高德确认 + 电梯...")
    results = []
    for i, c in enumerate(near):
        drive = f.amap_drive(c["coord"], tg)
        best = min(
            ((f.euclid(c["coord"], p), n, p) for n, p in stations.items()),
            key=lambda x: x[0],
        )
        walk = f.amap_walk_to_station(c["coord"], best[2])
        floors = f.floor_count(c["id"])
        ok = (
            drive
            and drive[1] < 40
            and walk is not None
            and walk < 10
            and floors
            and floors >= 7
        )
        # 该小区 7000-13000 的具体房源
        rents = [x for x in by_comm.get(c["name"], []) if LO <= int(x["price"]) <= HI]
        results.append(
            {
                "name": c["name"],
                "district": c["district"],
                "year": c["year"],
                "floors": floors,
                "km": c["km"],
                "drive": f"{drive[0]:.1f}km/{drive[1]:.0f}分" if drive else "-",
                "station": best[1],
                "walk": f"{walk:.0f}分" if walk is not None else "-",
                "rent_n": len(rents),
                "rent_min_max": f"{min(int(r['price']) for r in rents)}~{max(int(r['price']) for r in rents)}元/月"
                if rents
                else "-",
                "OK": "✓" if ok else "",
            }
        )
        if i % 8 == 0:
            sys.stderr.write(f"   高德 {i}/{len(near)}\n")
        time.sleep(0.3)

    results.sort(key=lambda r: (not r["OK"], r["walk"] == "-" and 1 or 0, r["km"]))
    with open(
        os.path.join(DATA, "rent_result.csv"), "w", newline="", encoding="utf-8-sig"
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
                "rent_min_max",
            ],
        )
        w.writeheader()
        w.writerows(results)
    print(f"\n共 {len(results)} 小区写入 data/rent_result.csv")
    for r in results:
        if r["OK"]:
            print(
                f"✓ {r['name']} {r['year']}年 {r['floors']}层 金钟路{r['drive']} 地铁{r['station']}步{r['walk']} 7000-13000:{r['rent_n']}套({r['rent_min_max']})"
            )


if __name__ == "__main__":
    main()
