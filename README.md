# QQuant

A股日线级别趋势波段交易系统。把炒股从"凭感觉操作"转变为可验证、可复盘、可迭代的系统工程。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 Tushare Token（不要写入代码或 config.yaml）
export TUSHARE_TOKEN="your_token_here"

# 下载数据（首次运行耗时较长）
python scripts/download_data.py

# 验证数据质量
python scripts/validate_data.py

# 运行回测
python scripts/run_backtest.py

# 生成每日信号报告
python scripts/daily_report.py
```

## 系统架构

```
data_loader      → 从 Tushare 下载原始数据
data_cleaner     → 前复权、标记ST/停牌/涨跌停
universe_filter  → 生成每日可交易股票池
indicators       → 计算技术指标（均线、量比、突破）
signal_engine    → 生成买入/卖出信号
signal_ranker    → 对买入候选按相对强度排序
risk_engine      → 仓位计算、风险暴露检查
backtester       → 历史回测（vectorbt）
portfolio_manager→ 持仓和成交记录管理
report_generator → 每日交易报告输出
monitor          → 异常监控
```

## 策略概述

- **股票池**：A股全市场，过滤ST/新股/停牌/低流动性
- **入场**：60日均线上方 + 20日均线向上 + 20日高点突破 + 放量 + 大盘在20日均线上方
- **排序**：相对强度评分（超额收益权重0.5 + 量比0.3 + 均线斜率0.2），取前15名
- **出场**：跌破20日均线 或 亏损7% 或 盈利15%后跌破10日均线
- **仓位**：单票≤15%，单笔风险≤1%账户，总仓位≤60%

## 风险提示

本项目仅用于学习、研究和个人系统设计，不构成投资建议。

## 进度

详见 [trading_system_plan.md](trading_system_plan.md)。
