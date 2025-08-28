"""
Risk management rules and position sizing
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
from abc import ABC, abstractmethod


class RiskRule(ABC):
    """Abstract base class for risk management rules"""
    
    @abstractmethod
    def check(self, position_info: Dict[str, Any], market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if risk rule is triggered
        
        Args:
            position_info: Current position information
            market_data: Current market data
            
        Returns:
            Dictionary with check results
        """
        pass


class StopLossRule(RiskRule):
    """Stop loss rule implementation"""
    
    def __init__(self, stop_loss_pct: float = 0.05):
        """
        Initialize stop loss rule
        
        Args:
            stop_loss_pct: Stop loss percentage (e.g., 0.05 = 5%)
        """
        self.stop_loss_pct = stop_loss_pct
        logger.debug(f"Stop loss rule initialized: {stop_loss_pct:.1%}")
    
    def check(self, position_info: Dict[str, Any], market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check stop loss condition"""
        if position_info.get('position', 0) <= 0:
            return {'triggered': False, 'action': None}
        
        entry_price = position_info.get('entry_price', 0)
        current_price = market_data.get('current_price', 0)
        
        if entry_price <= 0 or current_price <= 0:
            return {'triggered': False, 'action': None}
        
        # Calculate loss percentage
        loss_pct = (entry_price - current_price) / entry_price
        
        if loss_pct >= self.stop_loss_pct:
            return {
                'triggered': True,
                'action': 'sell',
                'reason': f'Stop loss triggered: {loss_pct:.2%} loss',
                'loss_pct': loss_pct,
                'stop_price': current_price
            }
        
        return {'triggered': False, 'action': None}


class TakeProfitRule(RiskRule):
    """Take profit rule implementation"""
    
    def __init__(self, take_profit_pct: float = 0.10):
        """
        Initialize take profit rule
        
        Args:
            take_profit_pct: Take profit percentage (e.g., 0.10 = 10%)
        """
        self.take_profit_pct = take_profit_pct
        logger.debug(f"Take profit rule initialized: {take_profit_pct:.1%}")
    
    def check(self, position_info: Dict[str, Any], market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check take profit condition"""
        if position_info.get('position', 0) <= 0:
            return {'triggered': False, 'action': None}
        
        entry_price = position_info.get('entry_price', 0)
        current_price = market_data.get('current_price', 0)
        
        if entry_price <= 0 or current_price <= 0:
            return {'triggered': False, 'action': None}
        
        # Calculate profit percentage
        profit_pct = (current_price - entry_price) / entry_price
        
        if profit_pct >= self.take_profit_pct:
            return {
                'triggered': True,
                'action': 'sell',
                'reason': f'Take profit triggered: {profit_pct:.2%} profit',
                'profit_pct': profit_pct,
                'take_profit_price': current_price
            }
        
        return {'triggered': False, 'action': None}


class PositionSizeRule(RiskRule):
    """Position sizing rule implementation"""
    
    def __init__(self, max_position_pct: float = 0.50, risk_per_trade_pct: float = 0.02):
        """
        Initialize position sizing rule
        
        Args:
            max_position_pct: Maximum position as percentage of portfolio (e.g., 0.50 = 50%)
            risk_per_trade_pct: Risk per trade as percentage of portfolio (e.g., 0.02 = 2%)
        """
        self.max_position_pct = max_position_pct
        self.risk_per_trade_pct = risk_per_trade_pct
        logger.debug(f"Position size rule initialized: max {max_position_pct:.1%}, risk {risk_per_trade_pct:.1%}")
    
    def check(self, position_info: Dict[str, Any], market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check position sizing constraints"""
        portfolio_value = position_info.get('portfolio_value', 0)
        current_position_value = position_info.get('position_value', 0)
        current_price = market_data.get('current_price', 0)
        proposed_shares = market_data.get('proposed_shares', 0)
        
        if portfolio_value <= 0 or current_price <= 0:
            return {'triggered': False, 'action': None}
        
        # Calculate position ratios
        current_position_pct = current_position_value / portfolio_value
        proposed_position_value = proposed_shares * current_price
        new_position_pct = (current_position_value + proposed_position_value) / portfolio_value
        
        # Check maximum position constraint
        if new_position_pct > self.max_position_pct:
            max_additional_value = portfolio_value * self.max_position_pct - current_position_value
            max_additional_shares = int(max_additional_value / current_price)
            
            return {
                'triggered': True,
                'action': 'limit_position',
                'reason': f'Position size limit: max {self.max_position_pct:.1%} of portfolio',
                'max_shares': max_additional_shares,
                'current_position_pct': current_position_pct,
                'proposed_position_pct': new_position_pct
            }
        
        return {'triggered': False, 'action': None}
    
    def calculate_position_size(
        self,
        portfolio_value: float,
        entry_price: float,
        stop_loss_price: float
    ) -> int:
        """
        Calculate optimal position size based on risk management
        
        Args:
            portfolio_value: Current portfolio value
            entry_price: Planned entry price
            stop_loss_price: Stop loss price
            
        Returns:
            Number of shares to buy
        """
        if portfolio_value <= 0 or entry_price <= 0 or stop_loss_price <= 0:
            return 0
        
        # Risk per share
        risk_per_share = abs(entry_price - stop_loss_price)
        
        if risk_per_share <= 0:
            return 0
        
        # Maximum risk amount
        max_risk_amount = portfolio_value * self.risk_per_trade_pct
        
        # Calculate shares based on risk
        risk_based_shares = int(max_risk_amount / risk_per_share)
        
        # Calculate shares based on maximum position
        max_position_value = portfolio_value * self.max_position_pct
        max_position_shares = int(max_position_value / entry_price)
        
        # Take the minimum
        optimal_shares = min(risk_based_shares, max_position_shares)
        
        logger.debug(f"Position size calculation: {optimal_shares} shares "
                    f"(risk-based: {risk_based_shares}, max-position: {max_position_shares})")
        
        return max(0, optimal_shares)


class TrailingStopRule(RiskRule):
    """Trailing stop loss rule implementation"""
    
    def __init__(self, trailing_pct: float = 0.05):
        """
        Initialize trailing stop rule
        
        Args:
            trailing_pct: Trailing stop percentage (e.g., 0.05 = 5%)
        """
        self.trailing_pct = trailing_pct
        self.highest_price = 0.0
        logger.debug(f"Trailing stop rule initialized: {trailing_pct:.1%}")
    
    def check(self, position_info: Dict[str, Any], market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check trailing stop condition"""
        if position_info.get('position', 0) <= 0:
            self.highest_price = 0.0
            return {'triggered': False, 'action': None}
        
        current_price = market_data.get('current_price', 0)
        
        if current_price <= 0:
            return {'triggered': False, 'action': None}
        
        # Update highest price
        if current_price > self.highest_price:
            self.highest_price = current_price
        
        # Calculate trailing stop price
        trailing_stop_price = self.highest_price * (1 - self.trailing_pct)
        
        if current_price <= trailing_stop_price:
            return {
                'triggered': True,
                'action': 'sell',
                'reason': f'Trailing stop triggered: price {current_price:.2f} <= stop {trailing_stop_price:.2f}',
                'trailing_stop_price': trailing_stop_price,
                'highest_price': self.highest_price
            }
        
        return {'triggered': False, 'action': None}
    
    def reset(self):
        """Reset trailing stop state"""
        self.highest_price = 0.0


class TimeBasedExitRule(RiskRule):
    """Time-based exit rule implementation"""
    
    def __init__(self, max_hold_days: int = 30):
        """
        Initialize time-based exit rule
        
        Args:
            max_hold_days: Maximum days to hold position
        """
        self.max_hold_days = max_hold_days
        logger.debug(f"Time-based exit rule initialized: {max_hold_days} days max hold")
    
    def check(self, position_info: Dict[str, Any], market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check time-based exit condition"""
        if position_info.get('position', 0) <= 0:
            return {'triggered': False, 'action': None}
        
        entry_date = position_info.get('entry_date')
        current_date = market_data.get('current_date')
        
        if not entry_date or not current_date:
            return {'triggered': False, 'action': None}
        
        # Calculate holding period
        hold_days = (current_date - entry_date).days
        
        if hold_days >= self.max_hold_days:
            return {
                'triggered': True,
                'action': 'sell',
                'reason': f'Time-based exit: held for {hold_days} days (max {self.max_hold_days})',
                'hold_days': hold_days
            }
        
        return {'triggered': False, 'action': None}


class RiskRules:
    """Collection of risk management rules"""
    
    def __init__(self):
        """Initialize risk rules collection"""
        self.rules = []
        logger.info("Risk rules collection initialized")
    
    def add_rule(self, rule: RiskRule):
        """Add a risk rule"""
        self.rules.append(rule)
        logger.debug(f"Added risk rule: {rule.__class__.__name__}")
    
    def remove_rule(self, rule_type: type):
        """Remove rules of specific type"""
        initial_count = len(self.rules)
        self.rules = [rule for rule in self.rules if not isinstance(rule, rule_type)]
        removed_count = initial_count - len(self.rules)
        logger.debug(f"Removed {removed_count} rules of type {rule_type.__name__}")
    
    def check_all_rules(
        self,
        position_info: Dict[str, Any],
        market_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Check all risk rules
        
        Args:
            position_info: Current position information
            market_data: Current market data
            
        Returns:
            List of triggered rule results
        """
        triggered_rules = []
        
        for rule in self.rules:
            try:
                result = rule.check(position_info, market_data)
                if result.get('triggered', False):
                    result['rule_type'] = rule.__class__.__name__
                    triggered_rules.append(result)
                    logger.debug(f"Rule triggered: {rule.__class__.__name__} - {result.get('reason', '')}")
            except Exception as e:
                logger.error(f"Error checking rule {rule.__class__.__name__}: {e}")
        
        return triggered_rules
    
    def get_rules_summary(self) -> Dict[str, Any]:
        """Get summary of active rules"""
        summary = {
            'total_rules': len(self.rules),
            'rule_types': {}
        }
        
        for rule in self.rules:
            rule_type = rule.__class__.__name__
            if rule_type not in summary['rule_types']:
                summary['rule_types'][rule_type] = 0
            summary['rule_types'][rule_type] += 1
        
        return summary