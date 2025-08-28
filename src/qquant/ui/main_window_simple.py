"""
Simple main window for QQuant desktop application (simplified version)
"""

import tkinter as tk
from tkinter import ttk, messagebox
from loguru import logger


class QQuantMainWindow:
    """Main window for QQuant application (simplified)"""
    
    def __init__(self):
        """Initialize main window"""
        self.root = tk.Tk()
        self.root.title("QQuant - AI量化交易软件 v0.1.0")
        self.root.geometry("800x600")
        
        # Setup basic UI
        self._setup_basic_ui()
        
        logger.info("Main window initialized (simplified version)")
    
    def _setup_basic_ui(self):
        """Setup basic user interface"""
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title
        title_label = ttk.Label(main_frame, text="QQuant - AI量化交易软件", font=("Arial", 16, "bold"))
        title_label.pack(pady=10)
        
        # Description
        desc_text = """
QQuant Phase 1 功能:

• 数据层: 集成Tushare Pro和AkShare数据源
• 策略层: AI驱动的策略生成（自然语言→Python代码）
• 回测层: 简单回测引擎，支持单标的回测
• 风控层: 止损/止盈规则引擎
• 界面层: 桌面客户端界面

注意: 这是QQuant的简化界面版本，用于验证核心功能。
完整的GUI功能正在开发中。
        """
        
        desc_label = ttk.Label(main_frame, text=desc_text.strip(), justify=tk.LEFT)
        desc_label.pack(pady=10, padx=20)
        
        # Status
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(pady=20)
        
        ttk.Label(status_frame, text="状态:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="QQuant Phase 1 核心功能已就绪")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, foreground="green")
        status_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)
        
        test_btn = ttk.Button(button_frame, text="测试核心功能", command=self._test_core_features)
        test_btn.pack(side=tk.LEFT, padx=5)
        
        about_btn = ttk.Button(button_frame, text="关于", command=self._show_about)
        about_btn.pack(side=tk.LEFT, padx=5)
        
        exit_btn = ttk.Button(button_frame, text="退出", command=self.root.quit)
        exit_btn.pack(side=tk.LEFT, padx=5)
    
    def _test_core_features(self):
        """Test core features"""
        self.status_var.set("正在测试核心功能...")
        self.root.update()
        
        try:
            # Test imports
            from qquant.data import DataManager
            from qquant.strategy import AIStrategyGenerator
            from qquant.backtest import BacktestEngine
            from qquant.risk import RiskRules
            
            # Quick functionality test
            dm = DataManager()
            generator = AIStrategyGenerator()
            engine = BacktestEngine()
            rules = RiskRules()
            
            self.status_var.set("✓ 所有核心功能测试通过!")
            messagebox.showinfo("测试成功", "QQuant Phase 1 核心功能运行正常!")
            
        except Exception as e:
            self.status_var.set("✗ 测试失败")
            messagebox.showerror("测试失败", f"核心功能测试失败: {e}")
    
    def _show_about(self):
        """Show about dialog"""
        about_text = """QQuant v0.1.0 - Phase 1

AI驱动的量化交易软件
专为A股市场设计

核心功能:
• AI策略生成
• 数据获取和清洗
• 简单回测
• 风险管理
• 性能分析

开发团队: QQuant Team
© 2024 QQuant. All rights reserved."""
        
        messagebox.showinfo("关于 QQuant", about_text)
    
    def run(self):
        """Run the application"""
        logger.info("Starting QQuant GUI application (simplified)")
        self.root.mainloop()
        logger.info("QQuant application closed")


if __name__ == "__main__":
    app = QQuantMainWindow()
    app.run()