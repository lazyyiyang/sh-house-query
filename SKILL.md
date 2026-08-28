---
name: sh-housing-query
description: 采集上海楼市/租房市场数据并按多条件筛选房源。Use when the task needs Shanghai real-estate or rental listings, community enumeration, second-hand deal records, commuter/metro distance screening, or geo/driving-time checks.
---

# 上海楼市 & 租房数据采集与选房

本项目是一套纯标准库 Python 工具（`C:\Users\zyy\sh-house-query`），采集上海住宅/租房数据并按硬约束筛选达标小区。零第三方依赖，输出 CSV 到 `data/`。

## 前置

- Python 3，无第三方包。
- 高德 Key 走环境变量 `AMAP_KEY`（缺失脚本会报错），**绝不硬编码**。
- 首次跑会缓存小区列表 `xiaoqu_all.json` 与地铁站 `metro.json`（约 2 分钟），之后秒回；缓存与结果均 `.gitignore`。

## 入口

通用采集 CLI（独立，不依赖共享层）：

```bash
python3 scripts/shfetch.py rent --region 浦东 --rtype 4        # 租赁平台挂牌
python3 scripts/shfetch.py dev  --months 12                    # 统计局房地产开发月度数据
python3 scripts/shfetch.py deal --name 康定大楼                 # 房天下二手房成交
python3 scripts/shfetch.py geo  --from 康定大楼 --to 人民广场     # 两点距离/耗时
```

多条件选房（均复用 `find_homes.py` 共享层，`import find_homes as f`）：

```bash
python3 scripts/find_buy_taiwu.py    # 太平洋二手房 500-800 万
python3 scripts/find_rent_taiwu.py   # 太平洋租房 7000-13000
python3 scripts/find_rent_fang.py    # 房天下租房
python3 scripts/find_rent_merged.py  # ★ 两源并集（最全）
python3 scripts/find_rent.py         # 上海租赁平台租房
```

## 共享层要点（find_homes.py）

- `taiwu_pull(ptype, areas, price_lo, price_hi)` —— 太平洋房屋分页 API，免鉴权，字段最权威（楼龄/电梯/地铁距离）。
- `enumerate_xiaoqu()` / `resolve_coord()` / `floor_count()` —— 房天下小区枚举、坐标、总层数判电梯。
- `get_metro_stations()` / `amap_drive()` / `amap_walk_to_station()` / `euclid()` —— 高德路线与几何。
- 常量：`TARGET="金钟路968号"`、`DISTRICTS`（长宁/静安）、`UA`。

## 数据源状态

| 来源 | 用途 | 状态 |
| --- | --- | --- |
| 太平洋房屋 `taiwuapigateway` | 买房/租房房源 | 免鉴权·字段最准 |
| 房天下 `fang.com` | 小区枚举 + 房源 | cookie 门 `otherid=MD5(...)`，覆盖最广 |
| 上海租赁平台 | 租房挂牌 | 免费·房源少 |
| 高德 Web 服务 | 地理编码/路线/地铁 | 需 Key |
| 链家/贝壳 | — | Geetest 极验，勿尝试 |

## 筛选口径（各 find 脚本硬编码）

区域长宁+静安，通勤点 `金钟路968号` 驾车 <40 分，地铁步行 <10 分，建成 >2000，电梯（`totalLayer>=7`）。

## 关键坑

- **地铁距离用官方字段**：太平洋 `nearMetroStationDistance≤600m` 才准；房天下坐标+高德步行不可靠（曾把 196m 算成 30+ 分）。
- **反爬接口脆弱**：房天下 cookie 公式、太平洋免鉴权 API 随时可能失效；解析靠正则，改前先抓真实页面确认 HTML 结构未变。
- 新筛选脚本只写差异化的拉取/过滤/输出，共享逻辑放 `find_homes.py`。
