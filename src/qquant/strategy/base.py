"""
Base strategy class for QQuant trading strategies
"""

from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any, Optional


class BaseStrategy(ABC):
    """Base class for all trading strategies"""
    
    def __init__(self, **params):
        """
        Initialize strategy with parameters
        
        Args:
            **params: Strategy parameters
        """
        self.params = params
        self.name = params.get('name', self.__class__.__name__)
        self.description = params.get('description', '')
        
        # Strategy state
        self.initialized = False
        self.current_position = 0
        self.trade_log = []
        
        # Risk management
        self.max_position_ratio = params.get('max_position_ratio', 0.5)
        self.stop_loss_ratio = params.get('stop_loss_ratio', 0.05)
        self.take_profit_ratio = params.get('take_profit_ratio', 0.10)
    
    @abstractmethod
    def initialize(self, data: pd.DataFrame) -> None:
        """
        Initialize strategy with historical data
        
        Args:
            data: Historical price data
        """
        pass
    
    @abstractmethod
    def next_bar(self, current_bar: pd.Series, portfolio: Dict[str, Any]) -> str:
        """
        Process next bar and generate signal
        
        Args:
            current_bar: Current bar data
            portfolio: Current portfolio state
            
        Returns:
            Trading signal: 'buy', 'sell', or 'hold'
        """
        pass
    
    def on_trade(self, trade_info: Dict[str, Any]) -> None:
        """
        Handle trade execution
        
        Args:
            trade_info: Trade information dictionary
        """
        self.trade_log.append(trade_info)
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get strategy parameters"""
        return self.params.copy()
    
    def set_parameter(self, key: str, value: Any) -> None:
        """Set strategy parameter"""
        self.params[key] = value
    
    def reset(self) -> None:
        """Reset strategy state"""
        self.initialized = False
        self.current_position = 0
        self.trade_log = []
    
    def get_trade_log(self) -> list:
        """Get trade log"""
        return self.trade_log.copy()
    
    def calculate_technical_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate common technical indicators
        
        Args:
            data: Price data
            
        Returns:
            Data with technical indicators
        """
        df = data.copy()
        
        # Moving averages
        for period in [5, 10, 20, 50]:
            df[f'MA_{period}'] = df['close'].rolling(period).mean()
            df[f'EMA_{period}'] = df['close'].ewm(span=period).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
        df['MACD_Histogram'] = df['MACD'] - df['MACD_Signal']
        
        # Bollinger Bands
        df['BB_Middle'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['BB_Upper'] = df['BB_Middle'] + 2 * bb_std
        df['BB_Lower'] = df['BB_Middle'] - 2 * bb_std
        
        # Volume indicators
        df['Volume_MA'] = df['volume'].rolling(20).mean() if 'volume' in df.columns else 0
        
        return df


class StrategyValidator:
    """Validator for strategy code"""
    
    @staticmethod
    def validate_strategy_code(code: str) -> Dict[str, Any]:
        """
        Validate strategy code for safety and correctness
        
        Args:
            code: Strategy code string
            
        Returns:
            Validation result dictionary
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        # Check for dangerous imports/functions
        dangerous_imports = [
            "os", "sys", "subprocess", "eval", "exec", "open", "file",
            "__import__", "globals", "locals", "vars"
        ]
        
        for dangerous in dangerous_imports:
            if dangerous in code:
                result["valid"] = False
                result["errors"].append(f"Dangerous function/import detected: {dangerous}")
        
        # Check for required methods
        required_methods = ["initialize", "next_bar"]
        for method in required_methods:
            if f"def {method}" not in code:
                result["valid"] = False
                result["errors"].append(f"Required method missing: {method}")
        
        # Check for BaseStrategy inheritance
        if "BaseStrategy" not in code:
            result["warnings"].append("Strategy should inherit from BaseStrategy")
        
        # Basic syntax check
        try:
            compile(code, "<strategy>", "exec")
        except SyntaxError as e:
            result["valid"] = False
            result["errors"].append(f"Syntax error: {e}")
        except Exception as e:
            result["warnings"].append(f"Compilation warning: {e}")
        
        return result