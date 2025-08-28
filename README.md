# QQuant - AI量化交易软件

QQuant是一个AI驱动的量化交易软件，专为A股市场设计。通过自然语言描述即可生成交易策略，并提供一键回测功能，大大降低量化交易的入门门槛。

## 🚀 Phase 1 功能特性

### 核心功能
- **AI策略生成**: 通过自然语言描述自动生成Python交易策略代码
- **数据接入**: 集成Tushare Pro和AkShare，提供A股日线数据
- **数据清洗**: 自动处理缺失值、停牌、复权等数据问题
- **简单回测**: 支持单标的、固定资金的回测
- **性能指标**: 输出收益曲线、最大回撤、胜率等关键指标
- **风险管理**: 内置止损/止盈规则引擎
- **桌面界面**: 简洁易用的桌面客户端

### 技术架构
```
qquant/
├── data/          # 数据层 - 数据获取、清洗、缓存
├── strategy/      # 策略层 - AI生成、编辑、验证
├── backtest/      # 回测层 - 回测引擎、组合管理、性能分析
├── risk/          # 风控层 - 风险规则、仓位管理
└── ui/           # 交互层 - 桌面界面
```

## 📦 安装和配置

### 环境要求
- Python 3.8+
- Windows/macOS/Linux

### 安装步骤

1. **克隆代码库**
```bash
git clone https://github.com/klifish/QQuant.git
cd QQuant
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置API密钥**
```bash
# 复制配置文件模板
cp config/secrets.env.example config/secrets.env

# 编辑配置文件，填入你的API密钥
# - Tushare Token: https://tushare.pro/register
# - OpenAI API Key: https://platform.openai.com/
```

4. **运行应用**
```bash
python -m qquant.main
# 或者
qquant
```

## 🎯 快速开始

### 1. 生成策略
- 打开"策略生成"标签页
- 输入自然语言策略描述，例如：
  - "5日均线上穿20日均线买入，跌5%止损"
  - "RSI低于30买入，高于70卖出"
  - "价格突破布林带上轨买入"
- 选择股票代码和初始资金
- 点击"生成策略"按钮

### 2. 配置回测
- 切换到"回测设置"标签页
- 设置回测日期范围
- 配置手续费率、滑点等参数
- 启用风险管理规则（止损/止盈）

### 3. 运行回测
- 点击"开始回测"按钮
- 等待回测完成
- 在"回测结果"标签页查看结果

### 4. 分析结果
- 查看绩效指标（收益率、回撤、夏普比率等）
- 分析收益曲线和回撤图表
- 导出详细结果到Excel

## 📊 示例策略

### 双均线策略
```
自然语言描述: "5日均线上穿20日均线买入，下穿卖出，跌5%止损"

生成的策略代码:
- 计算5日和20日移动平均线
- 金叉时买入，死叉时卖出
- 自动添加5%止损保护
```

### RSI均值回归策略
```
自然语言描述: "RSI低于30时买入，高于70时卖出"

生成的策略代码:
- 计算14日RSI指标
- RSI超卖区域买入
- RSI超买区域卖出
```

## 🛡️ 风险管理

### 内置风控功能
- **止损规则**: 支持固定百分比止损
- **止盈规则**: 支持固定百分比止盈
- **仓位限制**: 限制单个股票最大仓位
- **时间止损**: 支持最大持仓时间限制
- **异常监控**: 防止策略死循环

### 风控参数配置
```python
# 在界面中可配置:
stop_loss_ratio = 0.05      # 5%止损
take_profit_ratio = 0.10    # 10%止盈  
max_position_ratio = 0.50   # 最大50%仓位
```

## 📈 性能指标

QQuant提供全面的回测绩效分析：

### 收益指标
- 总收益率
- 年化收益率
- 超额收益（相对买入持有）
- 日均收益率

### 风险指标
- 最大回撤
- 年化波动率
- VaR（风险价值）
- 条件VaR

### 风险调整指标
- 夏普比率
- 索提诺比率
- 卡尔玛比率

### 交易统计
- 总交易次数
- 胜率
- 平均盈利/亏损
- 盈亏比

## 🔧 高级功能

### 自定义策略
除了AI生成，还支持手动编辑策略：

```python
from qquant.strategy.base import BaseStrategy

class MyCustomStrategy(BaseStrategy):
    def initialize(self, data):
        # 初始化指标
        self.data = self.calculate_technical_indicators(data)
        
    def next_bar(self, current_bar, portfolio):
        # 交易逻辑
        if self.data['RSI'].iloc[-1] < 30:
            return 'buy'
        elif self.data['RSI'].iloc[-1] > 70:
            return 'sell'
        return 'hold'
```

### 数据管理
- 支持数据缓存，提高加载速度
- 自动数据清洗和验证
- 支持多个数据源（Tushare、AkShare）

### 策略管理
- 策略保存和加载
- 策略导入导出
- 策略版本控制

## 🚧 开发路线图

### Phase 2 计划功能（增强版）
- **数据扩展**: 财务数据、新闻情绪分析
- **AI选股**: 智能选股推荐
- **风控增强**: AI风控助手、黑天鹅监控
- **多品种**: 支持更多股票品种

### Phase 3 计划功能（生态版）
- **策略市场**: 策略分享和订阅
- **社区功能**: 用户交流和排行榜
- **多市场**: 港股、美股支持
- **实盘对接**: 模拟盘和实盘交易

## 📝 API文档

### 数据层API
```python
from qquant.data import DataManager

# 初始化数据管理器
dm = DataManager()

# 获取股票数据
data = dm.get_stock_data("000001.SZ", "2024-01-01", "2024-12-31")

# 获取股票列表
stocks = dm.get_stock_list()
```

### 策略层API
```python
from qquant.strategy import AIStrategyGenerator

# AI策略生成
generator = AIStrategyGenerator()
strategy = generator.generate_strategy("双均线策略", "000001.SZ", 100000)
```

### 回测API
```python
from qquant.backtest import BacktestEngine

# 初始化回测引擎
engine = BacktestEngine(initial_capital=100000)

# 运行回测
results = engine.run_backtest(data, strategy, "000001.SZ")
```

## 🤝 贡献指南

欢迎贡献代码！请遵循以下步骤：

1. Fork本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建Pull Request

## 📋 许可证

本项目采用MIT许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## ⚠️ 免责声明

QQuant仅供学习和研究使用。使用本软件进行实际交易的任何损失，开发者不承担责任。投资有风险，入市需谨慎。

## 📞 联系我们

- 项目地址: https://github.com/klifish/QQuant
- 问题反馈: https://github.com/klifish/QQuant/issues
- 邮箱: qquant@example.com

## 🙏 致谢

感谢以下开源项目的支持：
- [Tushare](https://tushare.pro/) - 金融数据接口
- [AkShare](https://akshare.akfamily.xyz/) - 开源财经数据接口
- [OpenAI](https://openai.com/) - AI能力支持