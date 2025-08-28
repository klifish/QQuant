"""
Backtesting module for QQuant
Provides simple backtesting engine with performance metrics
"""

from .engine import BacktestEngine
from .portfolio import Portfolio
from .metrics import PerformanceMetrics
# from .visualizer import BacktestVisualizer  # Not implemented yet (requires matplotlib)

__all__ = ["BacktestEngine", "Portfolio", "PerformanceMetrics"]