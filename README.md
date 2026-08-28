# 上海楼市 & 租房市场数据分析

上海住宅/租赁数据采集 + 多条件选房筛选工具集。**纯标准库，零第三方依赖**（需一个免费的高德 Key）。

## 快速开始

```bash
# 高德 Key（必填，用环境变量，不写进代码）
export AMAP_KEY=你的高德Web服务Key   # lbs.amap.com 免费申请

# ① 通用采集 CLI（出租挂牌 / 宏观开发 / 二手房成交 / 两点距离）
python3 shfetch.py rent --region 浦东 --rtype 4
python3 shfetch.py dev  --months 12
python3 shfetch.py deal --name 康定大楼
python3 shfetch.py geo  --from 康定大楼 --to 人民广场

# ② 多条件选房（买房/租房，含 电梯/楼龄/通勤/地铁 筛选）
python3 find_buy_taiwu.py        # 太平洋二手房 500-800万
python3 find_rent_taiwu.py       # 太平洋租房 7000-13000
python3 find_rent_merged.py      # ★ 房天下+太平洋 并集（最全，40达标小区）
```

## 数据源实测结论（2026-08）

| 来源 | 用途 | 状态 |
| --- | --- | --- |
| 太平洋房屋 API `taiwuapigateway` | 买房/租房房源 | ✅ 免鉴权·官方核验·字段最准（楼龄/电梯/地铁距离/单价） |
| 房天下 (fang.com) | 小区枚举2937 + 房源 | ✅ cookie 门（`otherid=MD5(...)`）·覆盖最广 |
| 上海租赁平台 | 租房挂牌 | ✅ 免费·但房源少 |
| 高德 Web 服务 | 地理编码/路线/地铁 | ✅ 需免费 Key |
| 链家/贝壳 | — | ❌ Geetest 极验点选，难破解 |

## 关键洞察

- **「准」+「全」取长补短**：太平洋房屋字段权威（电梯/楼龄/地铁距离），房天下覆盖全（小区枚举+坐标）。`find_rent_merged.py` 并集后达标从 4/13 → **40**。
- **地铁<10分要用官方距离**：用房天下坐标+高德算步行**不可靠**（曾把离地铁196m算成30+分）；太平洋官方 `nearMetroStationDistance≤600m` 才准。
- **反爬逆向有维护风险**：房天下 cookie（MD5公式）、太平洋免鉴权 API 都是逆向接口，可能随时变更。

## 文件结构

```
shfetch.py           # 通用采集 CLI（rent/dev/deal/geo）
find_homes.py        # 共享基础层：cookie/key/taiwu_pull/枚举缓存/高德
find_buy_taiwu.py    # 太平洋二手房 500-800万
find_rent_taiwu.py   # 太平洋租房 7000-13000
find_rent_fang.py    # 房天下租房
find_rent_merged.py  # ★ 两源并集（最全）
find_rent.py         # 上海租赁平台租房
data/                # 缓存(xiaoqu_all/metro.json) + 结果CSV
```

## 注意事项

- `AMAP_KEY` 必须用环境变量（已移除硬编码；缺失脚本会报错）。
- `data/` 结果与缓存已 `.gitignore`；`xiaoqu_all.json`/`metro.json` 缓存，首次拉取慢（约2分钟），之后秒回。
