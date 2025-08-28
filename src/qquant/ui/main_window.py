"""
Main window for QQuant desktop application
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates

from qquant.data import DataManager
from qquant.strategy import AIStrategyGenerator, StrategyEditor
from qquant.backtest import BacktestEngine, PerformanceMetrics
from qquant.risk import RiskRules, StopLossRule, TakeProfitRule, PositionSizeRule


class QQuantMainWindow:
    """Main window for QQuant application"""
    
    def __init__(self):
        """Initialize main window"""
        self.root = tk.Tk()
        self.root.title("QQuant - AI量化交易软件 v0.1.0")
        self.root.geometry("1200x800")
        
        # Initialize components
        self.data_manager = DataManager()
        self.ai_generator = AIStrategyGenerator()
        self.strategy_editor = StrategyEditor()
        self.backtest_engine = BacktestEngine()
        self.performance_metrics = PerformanceMetrics()
        
        # Current state
        self.current_data = None
        self.current_strategy = None
        self.current_results = None
        
        # Setup UI
        self._setup_ui()
        self._setup_menu()
        
        logger.info("Main window initialized")
    
    def _setup_ui(self):
        """Setup the user interface"""
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create tabs
        self._create_strategy_tab()
        self._create_backtest_tab()
        self._create_results_tab()
        self._create_data_tab()
    
    def _setup_menu(self):
        """Setup menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="新建策略", command=self._new_strategy)
        file_menu.add_command(label="打开策略", command=self._open_strategy)
        file_menu.add_command(label="保存策略", command=self._save_strategy)
        file_menu.add_separator()
        file_menu.add_command(label="导出结果", command=self._export_results)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        
        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="工具", menu=tools_menu)
        tools_menu.add_command(label="数据缓存管理", command=self._manage_cache)
        tools_menu.add_command(label="设置", command=self._show_settings)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="使用说明", command=self._show_help)
        help_menu.add_command(label="关于", command=self._show_about)
    
    def _create_strategy_tab(self):
        """Create strategy input and generation tab"""
        strategy_frame = ttk.Frame(self.notebook)
        self.notebook.add(strategy_frame, text="策略生成")
        
        # Left panel - Strategy input
        left_frame = ttk.LabelFrame(strategy_frame, text="策略描述", padding="10")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        # Natural language input
        ttk.Label(left_frame, text="自然语言描述策略:").pack(anchor=tk.W)
        self.strategy_text = tk.Text(left_frame, height=6, width=50)
        self.strategy_text.pack(fill=tk.BOTH, expand=True, pady=(5, 10))
        
        # Example strategies
        ttk.Label(left_frame, text="示例策略:").pack(anchor=tk.W)
        example_frame = ttk.Frame(left_frame)
        example_frame.pack(fill=tk.X, pady=(5, 10))
        
        examples = [
            "5日均线上穿20日均线买入，跌5%止损",
            "RSI低于30买入，高于70卖出",
            "价格突破布林带上轨买入，跌破下轨卖出"
        ]
        
        self.example_var = tk.StringVar()
        example_combo = ttk.Combobox(example_frame, textvariable=self.example_var, values=examples, state="readonly")
        example_combo.pack(fill=tk.X)
        example_combo.bind("<<ComboboxSelected>>", self._load_example_strategy)
        
        # Stock symbol input
        symbol_frame = ttk.Frame(left_frame)
        symbol_frame.pack(fill=tk.X, pady=(5, 10))
        ttk.Label(symbol_frame, text="股票代码:").pack(side=tk.LEFT)
        self.symbol_var = tk.StringVar(value="000001.SZ")
        symbol_entry = ttk.Entry(symbol_frame, textvariable=self.symbol_var, width=15)
        symbol_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        # Initial capital input
        capital_frame = ttk.Frame(left_frame)
        capital_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(capital_frame, text="初始资金:").pack(side=tk.LEFT)
        self.capital_var = tk.StringVar(value="100000")
        capital_entry = ttk.Entry(capital_frame, textvariable=self.capital_var, width=15)
        capital_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        # Generate button
        generate_btn = ttk.Button(left_frame, text="生成策略", command=self._generate_strategy)
        generate_btn.pack(pady=10)
        
        # Right panel - Generated strategy
        right_frame = ttk.LabelFrame(strategy_frame, text="生成的策略代码", padding="10")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # Strategy code display
        self.strategy_code = tk.Text(right_frame, height=20, font=("Consolas", 10))
        self.strategy_code.pack(fill=tk.BOTH, expand=True)
        
        # Add scrollbar
        code_scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.strategy_code.yview)
        code_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.strategy_code.config(yscrollcommand=code_scrollbar.set)
    
    def _create_backtest_tab(self):
        """Create backtesting configuration tab"""
        backtest_frame = ttk.Frame(self.notebook)
        self.notebook.add(backtest_frame, text="回测设置")
        
        # Parameters frame
        params_frame = ttk.LabelFrame(backtest_frame, text="回测参数", padding="10")
        params_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Date range
        date_frame = ttk.Frame(params_frame)
        date_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(date_frame, text="开始日期:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.start_date_var = tk.StringVar(value=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"))
        start_date_entry = ttk.Entry(date_frame, textvariable=self.start_date_var)
        start_date_entry.grid(row=0, column=1, padx=(0, 20))
        
        ttk.Label(date_frame, text="结束日期:").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        self.end_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        end_date_entry = ttk.Entry(date_frame, textvariable=self.end_date_var)
        end_date_entry.grid(row=0, column=3)
        
        # Trading parameters
        trading_frame = ttk.Frame(params_frame)
        trading_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(trading_frame, text="手续费率:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.commission_var = tk.StringVar(value="0.001")
        commission_entry = ttk.Entry(trading_frame, textvariable=self.commission_var, width=10)
        commission_entry.grid(row=0, column=1, padx=(0, 20))
        
        ttk.Label(trading_frame, text="滑点率:").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        self.slippage_var = tk.StringVar(value="0.001")
        slippage_entry = ttk.Entry(trading_frame, textvariable=self.slippage_var, width=10)
        slippage_entry.grid(row=0, column=3)
        
        # Risk management
        risk_frame = ttk.LabelFrame(backtest_frame, text="风险管理", padding="10")
        risk_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Stop loss
        self.enable_stop_loss = tk.BooleanVar(value=True)
        stop_loss_check = ttk.Checkbutton(risk_frame, text="启用止损", variable=self.enable_stop_loss)
        stop_loss_check.grid(row=0, column=0, sticky=tk.W)
        
        ttk.Label(risk_frame, text="止损比例:").grid(row=0, column=1, sticky=tk.W, padx=(20, 5))
        self.stop_loss_var = tk.StringVar(value="0.05")
        stop_loss_entry = ttk.Entry(risk_frame, textvariable=self.stop_loss_var, width=10)
        stop_loss_entry.grid(row=0, column=2)
        
        # Take profit
        self.enable_take_profit = tk.BooleanVar(value=True)
        take_profit_check = ttk.Checkbutton(risk_frame, text="启用止盈", variable=self.enable_take_profit)
        take_profit_check.grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        
        ttk.Label(risk_frame, text="止盈比例:").grid(row=1, column=1, sticky=tk.W, padx=(20, 5), pady=(5, 0))
        self.take_profit_var = tk.StringVar(value="0.10")
        take_profit_entry = ttk.Entry(risk_frame, textvariable=self.take_profit_var, width=10)
        take_profit_entry.grid(row=1, column=2, pady=(5, 0))
        
        # Position sizing
        ttk.Label(risk_frame, text="最大仓位比例:").grid(row=2, column=0, sticky=tk.W, pady=(5, 0))
        self.max_position_var = tk.StringVar(value="0.50")
        max_position_entry = ttk.Entry(risk_frame, textvariable=self.max_position_var, width=10)
        max_position_entry.grid(row=2, column=1, padx=(5, 0), pady=(5, 0))\n        \n        # Run backtest button\n        run_frame = ttk.Frame(backtest_frame)\n        run_frame.pack(pady=20)\n        \n        self.run_backtest_btn = ttk.Button(run_frame, text=\"开始回测\", command=self._run_backtest)\n        self.run_backtest_btn.pack(side=tk.LEFT, padx=5)\n        \n        # Progress bar\n        self.progress_var = tk.StringVar(value=\"就绪\")\n        progress_label = ttk.Label(run_frame, textvariable=self.progress_var)\n        progress_label.pack(side=tk.LEFT, padx=(20, 0))\n    \n    def _create_results_tab(self):\n        \"\"\"Create results display tab\"\"\"\n        results_frame = ttk.Frame(self.notebook)\n        self.notebook.add(results_frame, text=\"回测结果\")\n        \n        # Create paned window for results\n        paned_window = ttk.PanedWindow(results_frame, orient=tk.HORIZONTAL)\n        paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)\n        \n        # Left panel - Performance metrics\n        metrics_frame = ttk.LabelFrame(paned_window, text=\"绩效指标\", padding=\"10\")\n        paned_window.add(metrics_frame, weight=1)\n        \n        self.metrics_text = tk.Text(metrics_frame, width=40, font=(\"Consolas\", 10))\n        self.metrics_text.pack(fill=tk.BOTH, expand=True)\n        \n        # Right panel - Charts\n        chart_frame = ttk.LabelFrame(paned_window, text=\"图表分析\", padding=\"10\")\n        paned_window.add(chart_frame, weight=2)\n        \n        # Matplotlib figure\n        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(10, 8))\n        self.canvas = FigureCanvasTkAgg(self.fig, chart_frame)\n        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)\n        \n        # Chart toolbar\n        from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk\n        toolbar = NavigationToolbar2Tk(self.canvas, chart_frame)\n        toolbar.update()\n    \n    def _create_data_tab(self):\n        \"\"\"Create data management tab\"\"\"\n        data_frame = ttk.Frame(self.notebook)\n        self.notebook.add(data_frame, text=\"数据管理\")\n        \n        # Stock selection\n        selection_frame = ttk.LabelFrame(data_frame, text=\"股票选择\", padding=\"10\")\n        selection_frame.pack(fill=tk.X, padx=5, pady=5)\n        \n        ttk.Label(selection_frame, text=\"股票代码:\").pack(side=tk.LEFT)\n        self.data_symbol_var = tk.StringVar(value=\"000001.SZ\")\n        symbol_entry = ttk.Entry(selection_frame, textvariable=self.data_symbol_var)\n        symbol_entry.pack(side=tk.LEFT, padx=(5, 20))\n        \n        load_btn = ttk.Button(selection_frame, text=\"加载数据\", command=self._load_data)\n        load_btn.pack(side=tk.LEFT)\n        \n        refresh_btn = ttk.Button(selection_frame, text=\"刷新数据\", command=self._refresh_data)\n        refresh_btn.pack(side=tk.LEFT, padx=(5, 0))\n        \n        # Data display\n        data_display_frame = ttk.LabelFrame(data_frame, text=\"数据预览\", padding=\"10\")\n        data_display_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)\n        \n        # Treeview for data display\n        columns = (\"日期\", \"开盘\", \"最高\", \"最低\", \"收盘\", \"成交量\")\n        self.data_tree = ttk.Treeview(data_display_frame, columns=columns, show=\"headings\", height=15)\n        \n        for col in columns:\n            self.data_tree.heading(col, text=col)\n            self.data_tree.column(col, width=100)\n        \n        self.data_tree.pack(fill=tk.BOTH, expand=True)\n        \n        # Scrollbars\n        data_v_scrollbar = ttk.Scrollbar(data_display_frame, orient=tk.VERTICAL, command=self.data_tree.yview)\n        data_v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)\n        self.data_tree.configure(yscrollcommand=data_v_scrollbar.set)\n    \n    def _load_example_strategy(self, event=None):\n        \"\"\"Load example strategy description\"\"\"\n        example = self.example_var.get()\n        if example:\n            self.strategy_text.delete(\"1.0\", tk.END)\n            self.strategy_text.insert(\"1.0\", example)\n    \n    def _generate_strategy(self):\n        \"\"\"Generate strategy from natural language description\"\"\"\n        description = self.strategy_text.get(\"1.0\", tk.END).strip()\n        symbol = self.symbol_var.get()\n        \n        try:\n            initial_capital = float(self.capital_var.get())\n        except ValueError:\n            messagebox.showerror(\"错误\", \"初始资金必须是数字\")\n            return\n        \n        if not description:\n            messagebox.showerror(\"错误\", \"请输入策略描述\")\n            return\n        \n        if not symbol:\n            messagebox.showerror(\"错误\", \"请输入股票代码\")\n            return\n        \n        # Show loading\n        self.progress_var.set(\"正在生成策略...\")\n        self.root.update()\n        \n        def generate_async():\n            try:\n                strategy = self.ai_generator.generate_strategy(\n                    description, symbol, initial_capital\n                )\n                \n                if strategy:\n                    self.current_strategy = strategy\n                    \n                    # Update UI in main thread\n                    self.root.after(0, lambda: self._display_generated_strategy(strategy))\n                else:\n                    self.root.after(0, lambda: messagebox.showerror(\"错误\", \"策略生成失败\"))\n                    \n            except Exception as e:\n                self.root.after(0, lambda: messagebox.showerror(\"错误\", f\"策略生成失败: {e}\"))\n            finally:\n                self.root.after(0, lambda: self.progress_var.set(\"就绪\"))\n        \n        # Run in background thread\n        threading.Thread(target=generate_async, daemon=True).start()\n    \n    def _display_generated_strategy(self, strategy):\n        \"\"\"Display generated strategy code\"\"\"\n        self.strategy_code.delete(\"1.0\", tk.END)\n        \n        display_text = f\"\"\"# {strategy['name']}\n# {strategy['description']}\n\n{strategy['code']}\n\n# 参数:\n{str(strategy.get('parameters', {}))}\n\n# 风险规则:\n{chr(10).join(strategy.get('risk_rules', []))}\"\"\"\n        \n        self.strategy_code.insert(\"1.0\", display_text)\n        messagebox.showinfo(\"成功\", f\"策略 '{strategy['name']}' 生成完成!\")\n    \n    def _load_data(self):\n        \"\"\"Load stock data\"\"\"\n        symbol = self.data_symbol_var.get()\n        \n        if not symbol:\n            messagebox.showerror(\"错误\", \"请输入股票代码\")\n            return\n        \n        self.progress_var.set(\"正在加载数据...\")\n        self.root.update()\n        \n        def load_async():\n            try:\n                # Load data for the past year\n                end_date = datetime.now().strftime(\"%Y-%m-%d\")\n                start_date = (datetime.now() - timedelta(days=365)).strftime(\"%Y-%m-%d\")\n                \n                data = self.data_manager.get_stock_data(symbol, start_date, end_date)\n                \n                if data is not None and not data.empty:\n                    self.current_data = data\n                    self.root.after(0, lambda: self._display_data(data))\n                    self.root.after(0, lambda: messagebox.showinfo(\"成功\", f\"已加载 {len(data)} 条数据记录\"))\n                else:\n                    self.root.after(0, lambda: messagebox.showerror(\"错误\", \"数据加载失败或无数据\"))\n                    \n            except Exception as e:\n                self.root.after(0, lambda: messagebox.showerror(\"错误\", f\"数据加载失败: {e}\"))\n            finally:\n                self.root.after(0, lambda: self.progress_var.set(\"就绪\"))\n        \n        threading.Thread(target=load_async, daemon=True).start()\n    \n    def _display_data(self, data):\n        \"\"\"Display data in treeview\"\"\"\n        # Clear existing data\n        for item in self.data_tree.get_children():\n            self.data_tree.delete(item)\n        \n        # Insert new data (show last 100 rows)\n        display_data = data.tail(100)\n        \n        for _, row in display_data.iterrows():\n            self.data_tree.insert(\"\", \"end\", values=(\n                row['date'].strftime(\"%Y-%m-%d\"),\n                f\"{row['open']:.2f}\",\n                f\"{row['high']:.2f}\",\n                f\"{row['low']:.2f}\",\n                f\"{row['close']:.2f}\",\n                f\"{row['volume']:,.0f}\"\n            ))\n    \n    def _refresh_data(self):\n        \"\"\"Refresh data (force reload)\"\"\"\n        symbol = self.data_symbol_var.get()\n        if symbol:\n            # Clear cache for this symbol\n            self.data_manager.clear_cache(symbol)\n            self._load_data()\n    \n    def _run_backtest(self):\n        \"\"\"Run backtest with current strategy\"\"\"\n        if not self.current_strategy:\n            messagebox.showerror(\"错误\", \"请先生成策略\")\n            return\n        \n        symbol = self.symbol_var.get()\n        \n        # Load data if not already loaded\n        if self.current_data is None:\n            start_date = self.start_date_var.get()\n            end_date = self.end_date_var.get()\n            \n            self.progress_var.set(\"正在加载数据...\")\n            self.root.update()\n            \n            try:\n                self.current_data = self.data_manager.get_stock_data(symbol, start_date, end_date)\n                if self.current_data is None or self.current_data.empty:\n                    messagebox.showerror(\"错误\", \"无法加载股票数据\")\n                    self.progress_var.set(\"就绪\")\n                    return\n            except Exception as e:\n                messagebox.showerror(\"错误\", f\"数据加载失败: {e}\")\n                self.progress_var.set(\"就绪\")\n                return\n        \n        self.progress_var.set(\"正在运行回测...\")\n        self.run_backtest_btn.config(state=\"disabled\")\n        self.root.update()\n        \n        def backtest_async():\n            try:\n                # Setup backtest parameters\n                commission = float(self.commission_var.get())\n                slippage = float(self.slippage_var.get())\n                initial_capital = float(self.capital_var.get())\n                \n                # Initialize backtest engine\n                self.backtest_engine = BacktestEngine(initial_capital, commission, slippage)\n                \n                # Create strategy instance (simplified)\n                strategy = self._create_strategy_instance()\n                \n                # Run backtest\n                results = self.backtest_engine.run_backtest(\n                    self.current_data,\n                    strategy,\n                    symbol,\n                    self.start_date_var.get(),\n                    self.end_date_var.get()\n                )\n                \n                self.current_results = results\n                \n                # Update UI in main thread\n                self.root.after(0, lambda: self._display_results(results))\n                self.root.after(0, lambda: messagebox.showinfo(\"成功\", \"回测完成!\"))\n                \n            except Exception as e:\n                self.root.after(0, lambda: messagebox.showerror(\"错误\", f\"回测失败: {e}\"))\n                logger.exception(\"Backtest failed\")\n            finally:\n                self.root.after(0, lambda: self.progress_var.set(\"就绪\"))\n                self.root.after(0, lambda: self.run_backtest_btn.config(state=\"normal\"))\n        \n        threading.Thread(target=backtest_async, daemon=True).start()\n    \n    def _create_strategy_instance(self):\n        \"\"\"Create a strategy instance from generated code\"\"\"\n        # This is a simplified implementation\n        # In a real application, you would need to safely execute the generated code\n        \n        class SimpleStrategy:\n            def __init__(self):\n                self.position = 0\n                self.data = None\n                \n            def initialize(self, data):\n                self.data = data.copy()\n                # Add simple moving averages\n                self.data['MA5'] = self.data['close'].rolling(5).mean()\n                self.data['MA20'] = self.data['close'].rolling(20).mean()\n                \n            def next_bar(self, current_bar, portfolio):\n                if len(self.data) < 20:\n                    return 'hold'\n                \n                current_idx = self.data.index[-1]\n                \n                if current_idx < 20:\n                    return 'hold'\n                \n                ma5_current = self.data.loc[current_idx, 'MA5']\n                ma20_current = self.data.loc[current_idx, 'MA20']\n                ma5_prev = self.data.loc[current_idx-1, 'MA5'] if current_idx > 0 else ma5_current\n                ma20_prev = self.data.loc[current_idx-1, 'MA20'] if current_idx > 0 else ma20_current\n                \n                # Simple MA crossover strategy\n                if ma5_prev <= ma20_prev and ma5_current > ma20_current and self.position == 0:\n                    self.position = 1\n                    return 'buy'\n                elif ma5_prev >= ma20_prev and ma5_current < ma20_current and self.position > 0:\n                    self.position = 0\n                    return 'sell'\n                \n                return 'hold'\n                \n            def on_trade(self, trade_info):\n                pass\n        \n        return SimpleStrategy()\n    \n    def _display_results(self, results):\n        \"\"\"Display backtest results\"\"\"\n        # Display metrics\n        metrics_text = f\"\"\"绩效报告\n\n基本指标:\n总收益率: {results['total_return']:.2%}\n基准收益率: {results['benchmark_return']:.2%}\n超额收益: {results['excess_return']:.2%}\n年化收益率: {results.get('annualized_return', 0):.2%}\n\n风险指标:\n最大回撤: {results.get('max_drawdown', 0):.2%}\n波动率: {results.get('annualized_volatility', 0):.2%}\n夏普比率: {results.get('sharpe_ratio', 0):.2f}\n\n交易统计:\n总交易次数: {results['trading_stats']['total_trades']}\n买入次数: {results['trading_stats']['buy_trades']}\n卖出次数: {results['trading_stats']['sell_trades']}\n胜率: {results.get('win_rate', 0):.2%}\n\n成本统计:\n总手续费: {results['trading_stats']['total_commission']:.2f}\n总滑点: {results['trading_stats']['total_slippage']:.2f}\n\n回测期间: {results['start_date'].strftime('%Y-%m-%d')} 至 {results['end_date'].strftime('%Y-%m-%d')}\n\"\"\"\n        \n        self.metrics_text.delete(\"1.0\", tk.END)\n        self.metrics_text.insert(\"1.0\", metrics_text)\n        \n        # Draw charts\n        self._draw_charts(results)\n        \n        # Switch to results tab\n        self.notebook.select(2)  # Results tab\n    \n    def _draw_charts(self, results):\n        \"\"\"Draw performance charts\"\"\"\n        self.ax1.clear()\n        self.ax2.clear()\n        \n        portfolio_values = results['portfolio_values']\n        \n        # Portfolio value chart\n        dates = pd.to_datetime(portfolio_values['date'])\n        values = portfolio_values['portfolio_value']\n        \n        self.ax1.plot(dates, values, 'b-', linewidth=2, label='策略收益')\n        \n        # Add benchmark (buy and hold)\n        price_data = self.current_data\n        price_data_filtered = price_data[price_data['date'].isin(dates)]\n        \n        if not price_data_filtered.empty:\n            initial_price = price_data_filtered['close'].iloc[0]\n            final_price = price_data_filtered['close'].iloc[-1]\n            initial_capital = float(self.capital_var.get())\n            \n            benchmark_values = (price_data_filtered['close'] / initial_price) * initial_capital\n            self.ax1.plot(price_data_filtered['date'], benchmark_values, 'r--', alpha=0.7, label='买入持有')\n        \n        self.ax1.set_title('投资组合价值')\n        self.ax1.set_ylabel('价值 (元)')\n        self.ax1.legend()\n        self.ax1.grid(True, alpha=0.3)\n        \n        # Format x-axis\n        self.ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))\n        self.ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))\n        \n        # Drawdown chart\n        running_max = values.expanding().max()\n        drawdown = (values - running_max) / running_max\n        \n        self.ax2.fill_between(dates, 0, drawdown, color='red', alpha=0.3)\n        self.ax2.plot(dates, drawdown, 'r-', linewidth=1)\n        self.ax2.set_title('回撤')\n        self.ax2.set_ylabel('回撤 (%)')\n        self.ax2.set_xlabel('日期')\n        self.ax2.grid(True, alpha=0.3)\n        \n        # Format x-axis\n        self.ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))\n        self.ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))\n        \n        plt.setp(self.ax1.xaxis.get_majorticklabels(), rotation=45)\n        plt.setp(self.ax2.xaxis.get_majorticklabels(), rotation=45)\n        \n        self.fig.tight_layout()\n        self.canvas.draw()\n    \n    # Menu callbacks\n    def _new_strategy(self):\n        \"\"\"Create new strategy\"\"\"\n        self.strategy_text.delete(\"1.0\", tk.END)\n        self.strategy_code.delete(\"1.0\", tk.END)\n        self.current_strategy = None\n        self.notebook.select(0)  # Strategy tab\n    \n    def _open_strategy(self):\n        \"\"\"Open saved strategy\"\"\"\n        strategies = self.strategy_editor.list_strategies()\n        \n        if not strategies:\n            messagebox.showinfo(\"信息\", \"没有找到已保存的策略\")\n            return\n        \n        # Simple strategy selection dialog\n        strategy_names = [s['name'] for s in strategies]\n        \n        dialog = tk.Toplevel(self.root)\n        dialog.title(\"选择策略\")\n        dialog.geometry(\"400x300\")\n        dialog.transient(self.root)\n        dialog.grab_set()\n        \n        listbox = tk.Listbox(dialog)\n        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)\n        \n        for name in strategy_names:\n            listbox.insert(tk.END, name)\n        \n        def on_select():\n            selection = listbox.curselection()\n            if selection:\n                selected_name = strategy_names[selection[0]]\n                strategy_data = self.strategy_editor.load_strategy(selected_name)\n                \n                if strategy_data:\n                    self.strategy_text.delete(\"1.0\", tk.END)\n                    self.strategy_text.insert(\"1.0\", strategy_data.get('description', ''))\n                    \n                    self.strategy_code.delete(\"1.0\", tk.END)\n                    self.strategy_code.insert(\"1.0\", strategy_data.get('code', ''))\n                    \n                    self.current_strategy = strategy_data\n                    messagebox.showinfo(\"成功\", f\"策略 '{selected_name}' 已加载\")\n                \n                dialog.destroy()\n        \n        button_frame = ttk.Frame(dialog)\n        button_frame.pack(pady=10)\n        \n        ttk.Button(button_frame, text=\"打开\", command=on_select).pack(side=tk.LEFT, padx=5)\n        ttk.Button(button_frame, text=\"取消\", command=dialog.destroy).pack(side=tk.LEFT, padx=5)\n    \n    def _save_strategy(self):\n        \"\"\"Save current strategy\"\"\"\n        if not self.current_strategy:\n            messagebox.showerror(\"错误\", \"没有策略需要保存\")\n            return\n        \n        try:\n            self.strategy_editor.create_strategy(\n                self.current_strategy['name'],\n                self.current_strategy['description'],\n                self.current_strategy['code'],\n                self.current_strategy.get('parameters', {}),\n                self.current_strategy.get('risk_rules', [])\n            )\n            messagebox.showinfo(\"成功\", f\"策略 '{self.current_strategy['name']}' 已保存\")\n        except Exception as e:\n            messagebox.showerror(\"错误\", f\"策略保存失败: {e}\")\n    \n    def _export_results(self):\n        \"\"\"Export backtest results\"\"\"\n        if not self.current_results:\n            messagebox.showerror(\"错误\", \"没有回测结果可导出\")\n            return\n        \n        filename = filedialog.asksaveasfilename(\n            defaultextension=\".xlsx\",\n            filetypes=[(\"Excel files\", \"*.xlsx\"), (\"All files\", \"*.*\")]\n        )\n        \n        if filename:\n            try:\n                with pd.ExcelWriter(filename) as writer:\n                    self.current_results['portfolio_values'].to_excel(writer, sheet_name='Portfolio Values', index=False)\n                    self.current_results['trades'].to_excel(writer, sheet_name='Trades', index=False)\n                    \n                    # Create metrics summary\n                    metrics_df = pd.DataFrame([\n                        ['Total Return', f\"{self.current_results['total_return']:.2%}\"],\n                        ['Benchmark Return', f\"{self.current_results['benchmark_return']:.2%}\"],\n                        ['Excess Return', f\"{self.current_results['excess_return']:.2%}\"],\n                        ['Max Drawdown', f\"{self.current_results.get('max_drawdown', 0):.2%}\"],\n                        ['Sharpe Ratio', f\"{self.current_results.get('sharpe_ratio', 0):.2f}\"],\n                        ['Total Trades', str(self.current_results['trading_stats']['total_trades'])]\n                    ], columns=['Metric', 'Value'])\n                    \n                    metrics_df.to_excel(writer, sheet_name='Summary', index=False)\n                \n                messagebox.showinfo(\"成功\", f\"结果已导出到 {filename}\")\n            except Exception as e:\n                messagebox.showerror(\"错误\", f\"导出失败: {e}\")\n    \n    def _manage_cache(self):\n        \"\"\"Manage data cache\"\"\"\n        cache_info = self.data_manager.get_cache_info()\n        \n        dialog = tk.Toplevel(self.root)\n        dialog.title(\"数据缓存管理\")\n        dialog.geometry(\"400x300\")\n        dialog.transient(self.root)\n        dialog.grab_set()\n        \n        info_text = f\"\"\"缓存信息:\n\n缓存数据记录: {cache_info.get('cached_data_count', 0)}\n缓存列表记录: {cache_info.get('cached_lists_count', 0)}\n缓存目录: {cache_info.get('cache_dir', 'N/A')}\n\"\"\"\n        \n        info_label = tk.Label(dialog, text=info_text, justify=tk.LEFT)\n        info_label.pack(padx=20, pady=20)\n        \n        button_frame = ttk.Frame(dialog)\n        button_frame.pack(pady=10)\n        \n        def clear_all_cache():\n            self.data_manager.clear_cache()\n            messagebox.showinfo(\"成功\", \"所有缓存已清除\")\n            dialog.destroy()\n        \n        ttk.Button(button_frame, text=\"清除所有缓存\", command=clear_all_cache).pack(side=tk.LEFT, padx=5)\n        ttk.Button(button_frame, text=\"关闭\", command=dialog.destroy).pack(side=tk.LEFT, padx=5)\n    \n    def _show_settings(self):\n        \"\"\"Show settings dialog\"\"\"\n        messagebox.showinfo(\"设置\", \"设置功能将在后续版本中提供\")\n    \n    def _show_help(self):\n        \"\"\"Show help dialog\"\"\"\n        help_text = \"\"\"QQuant 使用说明\n\n1. 策略生成:\n   - 在"策略生成"标签中输入自然语言描述\n   - 点击"生成策略"按钮生成Python代码\n   - 可以选择示例策略作为参考\n\n2. 回测设置:\n   - 在"回测设置"标签中配置回测参数\n   - 设置日期范围、手续费、滑点等\n   - 配置风险管理规则\n\n3. 查看结果:\n   - 在"回测结果"标签中查看绩效指标\n   - 分析收益曲线和回撤图表\n   - 导出详细结果到Excel\n\n4. 数据管理:\n   - 在"数据管理"标签中加载股票数据\n   - 查看数据预览\n   - 管理数据缓存\n\n更多信息请访问项目主页。\"\"\"\n        \n        dialog = tk.Toplevel(self.root)\n        dialog.title(\"使用说明\")\n        dialog.geometry(\"500x400\")\n        dialog.transient(self.root)\n        dialog.grab_set()\n        \n        text_widget = tk.Text(dialog, wrap=tk.WORD)\n        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)\n        text_widget.insert(\"1.0\", help_text)\n        text_widget.config(state=tk.DISABLED)\n        \n        ttk.Button(dialog, text=\"关闭\", command=dialog.destroy).pack(pady=10)\n    \n    def _show_about(self):\n        \"\"\"Show about dialog\"\"\"\n        about_text = \"\"\"QQuant v0.1.0\n\nAI驱动的量化交易软件\n专为A股市场设计\n\n功能特性:\n• AI策略生成\n• 一键回测\n• 风险管理\n• 结果可视化\n\n开发团队: QQuant Team\n项目地址: github.com/klifish/QQuant\n\n© 2024 QQuant. All rights reserved.\"\"\"\n        \n        messagebox.showinfo(\"关于 QQuant\", about_text)\n    \n    def run(self):\n        \"\"\"Run the application\"\"\"\n        logger.info(\"Starting QQuant GUI application\")\n        self.root.mainloop()\n        logger.info(\"QQuant application closed\")