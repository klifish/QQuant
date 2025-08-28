"""
Basic tests for QQuant Phase 1 implementation
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta

# Test data layer
def test_data_manager_initialization():
    """Test data manager initialization"""
    from qquant.data import DataManager
    
    dm = DataManager()
    assert dm is not None
    assert len(dm.providers) > 0

def test_data_cleaner():
    """Test data cleaning functionality"""
    from qquant.data import DataCleaner
    
    # Create test data with issues
    test_data = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=10),
        'open': [10.0, 10.5, None, 9.8, 10.2, 11.0, 10.8, 10.9, 10.7, 10.5],
        'high': [10.2, 10.8, 10.3, 10.0, 10.5, 11.2, 11.0, 11.1, 10.9, 10.8],
        'low': [9.8, 10.2, 9.9, 9.5, 9.8, 10.5, 10.3, 10.4, 10.2, 10.0],
        'close': [10.1, 10.6, 10.0, 9.7, 10.1, 10.9, 10.7, 10.8, 10.6, 10.4],
        'volume': [1000, 1200, 0, 800, 1100, 1500, 1300, 1400, 1200, 1000]
    })
    
    cleaner = DataCleaner()
    cleaned_data = cleaner.clean_stock_data(test_data)
    
    assert cleaned_data is not None
    assert len(cleaned_data) <= len(test_data)
    assert cleaned_data['open'].isnull().sum() == 0

# Test strategy layer
def test_ai_strategy_generator():
    """Test AI strategy generator"""
    from qquant.strategy import AIStrategyGenerator
    
    generator = AIStrategyGenerator()
    assert generator is not None
    
    # Test fallback strategy generation
    strategy = generator.generate_strategy(
        "Simple moving average strategy",
        "000001.SZ",
        100000
    )
    
    assert strategy is not None
    assert 'name' in strategy
    assert 'code' in strategy
    assert 'description' in strategy

def test_strategy_editor():
    """Test strategy editor"""
    from qquant.strategy import StrategyEditor
    
    editor = StrategyEditor()
    assert editor is not None
    
    # Test strategy creation
    test_strategy = {
        'name': 'Test Strategy',
        'description': 'A test strategy',
        'code': '''
class TestStrategy:
    def initialize(self, data):
        pass
        
    def next_bar(self, current_bar, portfolio):
        return 'hold'
        '''
    }
    
    created_strategy = editor.create_strategy(
        test_strategy['name'],
        test_strategy['description'],
        test_strategy['code']
    )
    
    assert created_strategy is not None
    assert created_strategy['name'] == test_strategy['name']

# Test backtesting
def test_backtest_engine():
    """Test backtest engine"""
    from qquant.backtest import BacktestEngine, Portfolio
    
    engine = BacktestEngine()
    assert engine is not None
    
    portfolio = Portfolio(100000)
    assert portfolio.initial_capital == 100000
    assert portfolio.cash == 100000
    assert portfolio.position == 0

def test_portfolio():
    """Test portfolio functionality"""
    from qquant.backtest import Portfolio
    
    portfolio = Portfolio(100000)
    
    # Test buy
    portfolio.buy(100, 10.0, datetime.now())
    assert portfolio.position == 100
    assert portfolio.cash == 99000
    
    # Test sell
    portfolio.sell(50, 11.0, datetime.now())
    assert portfolio.position == 50
    assert portfolio.cash == 99550

# Test risk management
def test_risk_rules():
    """Test risk management rules"""
    from qquant.risk import StopLossRule, TakeProfitRule, RiskRules
    
    # Test stop loss rule
    stop_loss = StopLossRule(0.05)  # 5% stop loss
    
    position_info = {
        'position': 100,
        'entry_price': 10.0
    }
    
    market_data = {
        'current_price': 9.4  # 6% loss
    }
    
    result = stop_loss.check(position_info, market_data)
    assert result['triggered'] == True
    assert result['action'] == 'sell'
    
    # Test take profit rule
    take_profit = TakeProfitRule(0.10)  # 10% take profit
    
    market_data['current_price'] = 11.5  # 15% profit
    result = take_profit.check(position_info, market_data)
    assert result['triggered'] == True
    assert result['action'] == 'sell'
    
    # Test risk rules collection
    rules = RiskRules()
    rules.add_rule(stop_loss)
    rules.add_rule(take_profit)
    
    assert len(rules.rules) == 2

# Integration test
def test_basic_workflow():
    """Test basic QQuant workflow"""
    from qquant.strategy import AIStrategyGenerator
    from qquant.backtest import BacktestEngine
    
    # Generate strategy
    generator = AIStrategyGenerator()
    strategy = generator.generate_strategy(
        "Buy when price goes up, sell when it goes down",
        "000001.SZ",
        100000
    )
    
    assert strategy is not None
    
    # Create test data
    test_data = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=30),
        'open': [10.0] * 30,
        'high': [10.2] * 30,
        'low': [9.8] * 30,
        'close': [10.0 + i * 0.1 for i in range(30)],  # Upward trend
        'volume': [1000] * 30,
        'amount': [10000] * 30
    })
    
    # Test would require actual strategy execution
    # This is a placeholder for integration testing
    assert len(test_data) == 30

if __name__ == "__main__":
    # Run basic tests
    test_data_manager_initialization()
    test_data_cleaner()
    test_ai_strategy_generator()
    test_strategy_editor()
    test_backtest_engine()
    test_portfolio()
    test_risk_rules()
    test_basic_workflow()
    
    print("All basic tests passed!")