"""
QQuant 系统健康监控面板（Streamlit）。

只监听本地回环（配合 SSH 隧道访问），盯三类关键指标：
  1. 关键状态：数据新鲜度 + 最近各定时任务成功/失败
  2. 数据规模：股票数、日线行数、覆盖区间
  3. 任务历史：解析 logs/*.log 的 SUCCESS/FAILURE 记录

运行：streamlit run dashboard/app.py
"""

import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.monitor import check_data_freshness

_ROOT = Path(__file__).parent.parent
LOG_DIR = _ROOT / "logs"
REPORT_DIR = _ROOT / "reports" / "daily"

st.set_page_config(page_title="QQuant 监控", page_icon="📈", layout="wide")

cfg = load_config()
DB_PATH = cfg["data"]["db_path"]


# ---------------------------------------------------------------------------
# 数据读取（缓存 5 分钟，避免每次刷新都全表扫描）
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300)
def get_db_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        def scalar(sql: str):
            return conn.execute(sql).fetchone()[0]

        stats = {
            "stock_basic": scalar("SELECT COUNT(*) FROM stock_basic"),
            "stock_daily": scalar("SELECT COUNT(*) FROM stock_daily"),
            "index_daily": scalar("SELECT COUNT(*) FROM index_daily"),
            "n_stocks": scalar("SELECT COUNT(DISTINCT ts_code) FROM stock_daily"),
            "min_date": scalar("SELECT MIN(trade_date) FROM stock_daily"),
            "max_date": scalar("SELECT MAX(trade_date) FROM stock_daily"),
            "st_rows": scalar("SELECT COUNT(*) FROM stock_daily WHERE is_st = 1"),
            "hs300_rows": scalar(
                "SELECT COUNT(*) FROM index_daily WHERE ts_code='399300.SZ'"
            ),
            "freshness_issues": check_data_freshness(conn),
        }
        return stats
    finally:
        conn.close()


@st.cache_data(ttl=60)
def parse_job_logs(limit: int = 30) -> pd.DataFrame:
    """解析 logs/*.log，提取每次任务的 job / 时间 / 结果。"""
    rows = []
    if not LOG_DIR.exists():
        return pd.DataFrame(columns=["任务", "时间", "结果", "文件"])

    for path in sorted(LOG_DIR.glob("*.log"), reverse=True):
        name = path.stem  # 形如 download_20260627_0900
        m = re.match(r"(download|validate|daily_report)_(\d{8})_(\d{4})", name)
        if not m:
            continue
        job, ymd, hm = m.groups()
        ts = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]} {hm[:2]}:{hm[2:]}"

        result = "运行中/未知"
        try:
            tail = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-6:]
            blob = "\n".join(tail)
            if "=== SUCCESS" in blob:
                result = "✅ SUCCESS"
            elif "=== FAILURE" in blob:
                result = "❌ FAILURE"
        except Exception:
            pass

        rows.append({"任务": job, "时间": ts, "结果": result, "文件": path.name})

    return pd.DataFrame(rows[:limit])


def latest_status(df: pd.DataFrame, job: str) -> str:
    sub = df[df["任务"] == job]
    if sub.empty:
        return "—（暂无记录）"
    r = sub.iloc[0]
    return f"{r['结果']}  ·  {r['时间']}"


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
st.title("📈 QQuant 系统健康监控")
st.caption(f"刷新时间：{datetime.now():%Y-%m-%d %H:%M:%S}（数据缓存 5 分钟）")

if st.button("🔄 强制刷新"):
    st.cache_data.clear()
    st.rerun()

try:
    stats = get_db_stats()
except Exception as e:
    st.error(f"读取数据库失败：{e}")
    st.stop()

logs_df = parse_job_logs()

# ---- 1. 关键状态 ----
st.header("① 关键状态")

fresh = not stats["freshness_issues"]
lag_text = "数据最新 ✅" if fresh else "；".join(stats["freshness_issues"])

c1, c2, c3, c4 = st.columns(4)
c1.metric("最新数据日期", stats["max_date"] or "无")
c2.metric("数据新鲜度", "正常" if fresh else "滞后", delta=None if fresh else lag_text,
          delta_color="off" if fresh else "inverse")
c3.metric("覆盖股票数", f"{stats['n_stocks']:,}")
c4.metric("清洗状态(ST标记)", "已清洗" if stats["st_rows"] > 0 else "未清洗 ⚠️")

if not fresh:
    st.warning("⚠️ " + lag_text)

st.subheader("最近各定时任务")
j1, j2, j3 = st.columns(3)
j1.metric("数据下载 download", "")
j1.write(latest_status(logs_df, "download"))
j2.metric("数据校验 validate", "")
j2.write(latest_status(logs_df, "validate"))
j3.metric("日报生成 daily_report", "")
j3.write(latest_status(logs_df, "daily_report"))

# ---- 2. 数据规模 ----
st.header("② 数据规模")
d1, d2, d3, d4 = st.columns(4)
d1.metric("股票基础", f"{stats['stock_basic']:,}")
d2.metric("日线行数", f"{stats['stock_daily']:,}")
d3.metric("覆盖区间", f"{stats['min_date']} ~ {stats['max_date']}")
d4.metric("沪深300日线", f"{stats['hs300_rows']:,}")

# ---- 3. 任务历史 ----
st.header("③ 任务历史")
if logs_df.empty:
    st.info("暂无任务日志（logs/ 目录为空，cron 跑过后会出现）")
else:
    def color_result(val):
        if "SUCCESS" in str(val):
            return "color: #16a34a"
        if "FAILURE" in str(val):
            return "color: #dc2626"
        return ""
    st.dataframe(
        logs_df.style.map(color_result, subset=["结果"]),
        use_container_width=True,
        hide_index=True,
    )

# ---- 最新日报快捷查看 ----
st.header("📄 最新日报")
if REPORT_DIR.exists():
    reports = sorted(REPORT_DIR.glob("*.md"), reverse=True)
    if reports:
        latest = reports[0]
        st.caption(f"文件：{latest.name}")
        with st.expander("展开查看", expanded=False):
            st.markdown(latest.read_text(encoding="utf-8", errors="ignore"))
    else:
        st.info("暂无日报")
else:
    st.info("reports/daily 目录尚不存在")
