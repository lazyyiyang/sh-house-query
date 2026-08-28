# AGENT.md

上海楼市 & 租房市场数据采集 + 多条件选房筛选工具集。

## 技术约束

- **Python 3，纯标准库，零第三方依赖**（`urllib`/`re`/`json`/`csv`/`gzip`/`hashlib`）。不要引入 requests/pandas 等依赖。
- 输出 CSV 一律 `encoding="utf-8-sig"`（Excel 兼容），写入 `data/`。
- 无测试、无包结构、无 lint 配置——就是几个可独立运行的脚本。

## 运行前置

- 高德 Key 走环境变量 `AMAP_KEY`（`find_homes.get_key()` 缺失即 `SystemExit`）。**绝不硬编码 Key。**
- 缓存与结果在 `data/`（`xiaoqu_all.json`/`metro.json`/各 CSV），已 `.gitignore`。首次拉取小区/地铁缓存约 2 分钟，之后秒回。

## 文件职责

- `find_homes.py` —— **共享基础层**，其余 `find_*.py` 一律 `import find_homes as f` 复用：
  - `_fang()`/`_amap()` 请求封装；`_otherid()` 房天下 cookie（MD5 公式）
  - `taiwu_pull()` 太平洋房屋分页 API（免鉴权，字段权威）
  - `enumerate_xiaoqu()` 小区枚举（磁盘缓存）、`resolve_coord()`、`floor_count()`
  - `get_metro_stations()`、`euclid()`、`amap_drive()`、`amap_walk_to_station()`
  - 常量：`TARGET="金钟路968号"`、`DISTRICTS`（长宁/静安）、`UA`
- `shfetch.py` —— **独立通用采集 CLI**（`rent`/`dev`/`deal`/`geo`），不 import find_homes。
- `find_buy_taiwu.py` —— 太平洋二手房 500-800 万
- `find_rent_taiwu.py` —— 太平洋租房 7000-13000
- `find_rent_fang.py` —— 房天下租房
- `find_rent_merged.py` —— ★ 两源并集（最全）
- `find_rent.py` —— 上海租赁平台租房

## 数据源（实测结论）

| 来源 | 用途 | 备注 |
| --- | --- | --- |
| 太平洋房屋 `taiwuapigateway` | 买房/租房房源 | 免鉴权·字段最准（楼龄/电梯/地铁距离） |
| 房天下 `fang.com` | 小区枚举 + 房源 | cookie 门 `otherid=MD5(...)`，覆盖最广 |
| 上海租赁平台 | 租房挂牌 | 免费但房源少 |
| 高德 Web 服务 | 地理编码/路线/地铁 | 需 `AMAP_KEY` |
| 链家/贝壳 | — | Geetest 极验，难破解（勿浪费时间） |

## 筛选口径（各 find 脚本硬编码）

- 区域：长宁 + 静安（`AREAS=[3,4]`，或房天下 `a020`/`a021`）
- 目标通勤点：`金钟路968号`，驾车 < 40 分
- 地铁：步行 < 10 分（或官方 `nearMetroStationDistance ≤ 600m`）
- 楼龄：建成 > 2000（`year >= 2001`）
- 电梯：`totalLayer >= 7` 或 `elevatorTag` 判电梯

## 关键坑

- **地铁距离用官方字段，别用坐标算**：房天下坐标 + 高德步行不可靠（曾把 196m 算成 30+ 分）；太平洋 `nearMetroStationDistance` 才准。
- **反爬接口脆弱**：房天下 cookie（`ETFio#dr`+时间戳 MD5）、太平洋免鉴权 API 都是逆向接口，随时可能失效；改动时留意 HTML 结构变化。
- 大量 `re` 靠正则解析 HTML，改解析逻辑前先抓一份真实页面确认结构没变。

## 修改约定

- 共享逻辑放 `find_homes.py`，新筛选脚本只写差异化的拉取/过滤/输出。
- 不要手写测试框架；改动非平凡逻辑留一个最小 `assert` 自检即可。
