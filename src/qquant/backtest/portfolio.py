"""
Portfolio management for backtesting
"""

import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional
from loguru import logger


class Portfolio:
    """Simple portfolio for single stock trading"""
    
    def __init__(self, initial_capital: float):
        """
        Initialize portfolio
        
        Args:
            initial_capital: Initial cash amount
        """
        self.initial_capital = initial_capital
        self.reset(initial_capital)
    
    def reset(self, initial_capital: float):
        """Reset portfolio to initial state"""
        self.cash = initial_capital
        self.position = 0  # Number of shares held
        self.total_value = initial_capital
        self.last_price = 0
        self.last_update = None
        
        logger.debug(f"Portfolio reset with capital: {initial_capital}")
    
    def buy(self, shares: int, price: float, date: datetime):
        """
        Execute buy order
        
        Args:
            shares: Number of shares to buy
            price: Price per share (including costs)
            date: Transaction date
        """
        total_cost = shares * price
        
        if total_cost > self.cash:
            raise ValueError(f"Insufficient cash: need {total_cost}, have {self.cash}")
        
        self.cash -= total_cost
        self.position += shares
        self.last_price = price
        self.last_update = date
        
        self._update_total_value()
        
        logger.debug(f"Bought {shares} shares at {price:.2f}, cash: {self.cash:.2f}")
    
    def sell(self, shares: int, price: float, date: datetime):
        """
        Execute sell order
        
        Args:
            shares: Number of shares to sell
            price: Price per share (after costs)
            date: Transaction date
        """
        if shares > self.position:
            raise ValueError(f"Insufficient shares: trying to sell {shares}, have {self.position}")
        
        total_proceeds = shares * price
        
        self.cash += total_proceeds
        self.position -= shares
        self.last_price = price
        self.last_update = date
        
        self._update_total_value()
        
        logger.debug(f"Sold {shares} shares at {price:.2f}, cash: {self.cash:.2f}")
    
    def update_value(self, current_price: float, date: datetime):
        """
        Update portfolio value based on current market price
        
        Args:
            current_price: Current stock price
            date: Current date
        """
        self.last_price = current_price
        self.last_update = date
        self._update_total_value()
    
    def _update_total_value(self):
        """Update total portfolio value"""
        position_value = self.position * self.last_price
        self.total_value = self.cash + position_value
    
    def get_state(self) -> Dict[str, Any]:
        """Get current portfolio state"""
        return {
            'cash': self.cash,
            'position': self.position,
            'last_price': self.last_price,
            'position_value': self.position * self.last_price,
            'total_value': self.total_value,
            'last_update': self.last_update
        }
    
    def get_position_ratio(self) -> float:
        """Get position as ratio of total value"""
        if self.total_value == 0:
            return 0.0
        
        return (self.position * self.last_price) / self.total_value
    
    def get_cash_ratio(self) -> float:
        """Get cash as ratio of total value"""
        if self.total_value == 0:
            return 0.0
        
        return self.cash / self.total_value
    
    def get_unrealized_pnl(self, entry_price: float) -> float:
        """
        Calculate unrealized P&L
        
        Args:
            entry_price: Average entry price
            
        Returns:
            Unrealized P&L
        """
        if self.position == 0:
            return 0.0
        
        return self.position * (self.last_price - entry_price)
    
    def get_total_return(self) -> float:
        """Get total return since inception"""
        return (self.total_value - self.initial_capital) / self.initial_capital
    
    def is_long(self) -> bool:
        """Check if portfolio has long position"""
        return self.position > 0
    
    def is_short(self) -> bool:
        """Check if portfolio has short position"""
        return self.position < 0
    
    def is_flat(self) -> bool:
        """Check if portfolio has no position"""
        return self.position == 0
    
    def can_buy(self, shares: int, price: float) -> bool:
        """Check if portfolio can buy specified shares"""
        return self.cash >= shares * price
    
    def can_sell(self, shares: int) -> bool:
        """Check if portfolio can sell specified shares"""
        return self.position >= shares
    
    def get_max_buy_shares(self, price: float) -> int:
        """Get maximum shares that can be bought"""
        if price <= 0:
            return 0
        
        return int(self.cash / price)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get portfolio summary"""
        return {
            'initial_capital': self.initial_capital,
            'current_cash': self.cash,
            'current_position': self.position,
            'last_price': self.last_price,
            'position_value': self.position * self.last_price if self.last_price > 0 else 0,
            'total_value': self.total_value,
            'total_return': self.get_total_return(),
            'position_ratio': self.get_position_ratio(),
            'cash_ratio': self.get_cash_ratio(),
            'last_update': self.last_update
        }