#!/usr/bin/env python3
"""太平洋房屋二手房筛选：长宁+静安，500-800万，电梯房>2000年，到金钟路968号<40分，地铁<10分。

复用 find_homes.taiwu_pull(ptype=1)；地铁用官方 nearMetroStationDistance(≤600m)；金钟路用高德驾车。
用法：python3 find_buy_taiwu.py
输出：data/taiwu_buy_result.csv
"""

import csv
import os
import sys
import time

import find_homes as f

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA, exist_ok=True)
PRICE_LO, PRICE_HI = 500, 800  # 万
AREAS = [3, 4]


def main():
    print("1) 拉取太平洋房屋 长宁+静安 500-800万...")
    li = f.taiwu_pull(ptype=1, areas=AREAS, price_lo=PRICE_LO, price_hi=PRICE_HI)
    print(f"   → {len(li)} 条")
    cand = [
        x
        for x in li
        if x.get("areaName") in ("长宁", "静安")
        and str(x.get("createYear", "0"))[:4].isdigit()
        and int(str(x.get("createYear"))[:4]) >= 2001
        and (x.get("elevatorTag") or (x.get("totalLayer") or 0) >= 7)
        and PRICE_LO <= int(x.get("price") or 0) <= PRICE_HI
    ]
    print(f"2) 建成>2000 + 电梯 + 500-800万: {len(cand)} 条")
    from collections import defaultdict

    agg = defaultdict(list)
    for x in cand:
        agg[x["estateName"]].append(x)
    print(f"3) 涉及小区: {len(agg)}")

    tg = tuple(
        map(
            float,
            f._amap("/geocode/geo", {"address": f.TARGET, "city": "上海"})["geocodes"][
                0
            ]["location"].split(","),
        )
    )
    stations = f.get_metro_stations()
    print(f"   目标{tg}, 地铁站{len(stations)}")

    results = []
    for i, (ename, homes) in enumerate(agg.items()):
        coord = f.resolve_coord(ename)
        if not coord:
            continue
        km = round(f.euclid(coord, tg), 2)
        if km >= 8:
            continue
        drive = f.amap_drive(coord, tg)
        mdist = min([h.get("nearMetroStationDistance") or 999999 for h in homes])
        ok = drive and drive[1] < 40 and mdist <= 600
        results.append(
            {
                "name": ename,
                "area": homes[0]["areaName"],
                "year": homes[0].get("createYear"),
                "totalLayer": homes[0].get("totalLayer"),
                "km": km,
                "drive": f"{drive[0]:.1f}km/{drive[1]:.0f}分" if drive else "-",
                "metro_d": mdist if mdist < 999999 else "-",
                "sale_n": len(homes),
                "sale_info": " | ".join(
                    f"{h['roomNum']}室{h['hallNum']}厅{h['propertySquare']}㎡{h['price']}万({h['priceUnit']}元/㎡)"
                    for h in homes[:4]
                ),
                "OK": "✓" if ok else "",
            }
        )
        if i % 8 == 0:
            sys.stderr.write(f"   高德 {i}/{len(agg)}\n")
        time.sleep(0.3)

    results.sort(key=lambda r: (not r["OK"], r["km"]))
    with open(
        os.path.join(DATA, "taiwu_buy_result.csv"),
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as fp:
        w = csv.DictWriter(
            fp,
            fieldnames=[
                "OK",
                "name",
                "area",
                "year",
                "totalLayer",
                "km",
                "drive",
                "metro_d",
                "sale_n",
                "sale_info",
            ],
        )
        w.writeheader()
        w.writerows(results)
    print(f"\n共 {len(results)} 小区写入 data/taiwu_buy_result.csv")
    for r in results:
        if r["OK"]:
            print(
                f"✓ {r['name']} {r['area']} {r['year']}年 金钟路{r['drive']} 地铁{r['metro_d']} 房源{r['sale_n']}套\n     {r['sale_info']}"
            )


if __name__ == "__main__":
    main()
