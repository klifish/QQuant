"""
Performance metrics calculation for backtesting results
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger


class PerformanceMetrics:
    """Calculate various performance metrics for backtesting results"""
    
    def __init__(self):
        """Initialize performance metrics calculator"""
        self.risk_free_rate = 0.03  # 3% annual risk-free rate
    
    def calculate_metrics(
        self,
        returns: pd.Series,
        portfolio_values: pd.Series,
        benchmark_return: float = 0.0
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive performance metrics
        
        Args:
            returns: Series of daily returns
            portfolio_values: Series of portfolio values
            benchmark_return: Benchmark total return
            
        Returns:
            Dictionary of performance metrics
        """
        if returns.empty or portfolio_values.empty:
            return self._get_empty_metrics()
        
        try:
            metrics = {}
            
            # Basic return metrics
            metrics.update(self._calculate_return_metrics(returns, portfolio_values))
            
            # Risk metrics
            metrics.update(self._calculate_risk_metrics(returns, portfolio_values))
            
            # Risk-adjusted metrics
            metrics.update(self._calculate_risk_adjusted_metrics(returns))
            
            # Drawdown metrics
            metrics.update(self._calculate_drawdown_metrics(portfolio_values))
            
            # Trading metrics
            metrics.update(self._calculate_trading_metrics(returns))
            
            # Benchmark comparison
            metrics.update(self._calculate_benchmark_metrics(returns, benchmark_return))
            
            logger.debug("Performance metrics calculated successfully")
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating performance metrics: {e}")
            return self._get_empty_metrics()
    
    def _calculate_return_metrics(self, returns: pd.Series, portfolio_values: pd.Series) -> Dict[str, float]:
        """Calculate return-based metrics"""
        total_return = (portfolio_values.iloc[-1] - portfolio_values.iloc[0]) / portfolio_values.iloc[0]
        
        # Annualize returns (assuming daily data)
        trading_days = len(returns)
        years = trading_days / 252.0  # 252 trading days per year
        
        if years > 0:
            annualized_return = (1 + total_return) ** (1 / years) - 1
        else:
            annualized_return = 0.0
        
        # Average daily return
        avg_daily_return = returns.mean()
        
        return {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'avg_daily_return': avg_daily_return,
            'trading_days': trading_days
        }
    
    def _calculate_risk_metrics(self, returns: pd.Series, portfolio_values: pd.Series) -> Dict[str, float]:
        """Calculate risk-based metrics"""
        # Volatility
        daily_volatility = returns.std()
        annualized_volatility = daily_volatility * np.sqrt(252)
        
        # Value at Risk (95% confidence)
        var_95 = returns.quantile(0.05)
        
        # Conditional Value at Risk (Expected Shortfall)
        cvar_95 = returns[returns <= var_95].mean()
        
        return {
            'daily_volatility': daily_volatility,
            'annualized_volatility': annualized_volatility,
            'var_95': var_95,
            'cvar_95': cvar_95
        }
    
    def _calculate_risk_adjusted_metrics(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate risk-adjusted metrics"""
        avg_return = returns.mean()
        volatility = returns.std()
        
        # Sharpe ratio (annualized)
        if volatility > 0:
            daily_rf_rate = self.risk_free_rate / 252
            sharpe_ratio = (avg_return - daily_rf_rate) / volatility * np.sqrt(252)
        else:
            sharpe_ratio = 0.0
        
        # Sortino ratio (using downside deviation)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0:
            downside_deviation = downside_returns.std()
            if downside_deviation > 0:
                sortino_ratio = (avg_return * 252) / (downside_deviation * np.sqrt(252))
            else:
                sortino_ratio = 0.0
        else:
            sortino_ratio = float('inf')
        
        # Calmar ratio (annualized return / max drawdown)
        # Will be calculated in drawdown metrics
        
        return {
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio
        }
    
    def _calculate_drawdown_metrics(self, portfolio_values: pd.Series) -> Dict[str, float]:
        """Calculate drawdown-based metrics"""
        # Calculate running maximum
        running_max = portfolio_values.expanding().max()
        
        # Calculate drawdown
        drawdown = (portfolio_values - running_max) / running_max
        
        # Maximum drawdown
        max_drawdown = drawdown.min()
        
        # Maximum drawdown duration
        is_drawdown = drawdown < 0
        
        if is_drawdown.any():
            # Find drawdown periods
            drawdown_starts = is_drawdown & ~is_drawdown.shift(1, fill_value=False)
            drawdown_ends = ~is_drawdown & is_drawdown.shift(1, fill_value=False)
            
            if drawdown_starts.sum() > 0:
                max_drawdown_duration = 0
                current_duration = 0
                
                for i in range(len(is_drawdown)):
                    if is_drawdown.iloc[i]:
                        current_duration += 1
                        max_drawdown_duration = max(max_drawdown_duration, current_duration)
                    else:
                        current_duration = 0
            else:
                max_drawdown_duration = 0
        else:
            max_drawdown_duration = 0
        
        # Calmar ratio
        total_return = (portfolio_values.iloc[-1] - portfolio_values.iloc[0]) / portfolio_values.iloc[0]
        years = len(portfolio_values) / 252.0
        
        if years > 0:
            annualized_return = (1 + total_return) ** (1 / years) - 1
            if max_drawdown < 0:
                calmar_ratio = annualized_return / abs(max_drawdown)
            else:
                calmar_ratio = float('inf')
        else:
            calmar_ratio = 0.0
        
        return {
            'max_drawdown': max_drawdown,
            'max_drawdown_duration': max_drawdown_duration,
            'calmar_ratio': calmar_ratio,
            'current_drawdown': drawdown.iloc[-1]
        }
    
    def _calculate_trading_metrics(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate trading-specific metrics"""
        # Win rate
        winning_days = returns[returns > 0]
        losing_days = returns[returns < 0]
        
        total_trading_days = len(returns[returns != 0])
        
        if total_trading_days > 0:
            win_rate = len(winning_days) / total_trading_days
        else:
            win_rate = 0.0
        
        # Average win/loss
        avg_win = winning_days.mean() if len(winning_days) > 0 else 0.0
        avg_loss = losing_days.mean() if len(losing_days) > 0 else 0.0
        
        # Profit factor
        if avg_loss != 0:
            profit_factor = abs(avg_win / avg_loss)
        else:
            profit_factor = float('inf') if avg_win > 0 else 0.0
        
        # Expected value
        expected_value = win_rate * avg_win + (1 - win_rate) * avg_loss
        
        return {
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'expected_value': expected_value,
            'total_trading_days': total_trading_days
        }
    
    def _calculate_benchmark_metrics(self, returns: pd.Series, benchmark_return: float) -> Dict[str, float]:
        """Calculate benchmark comparison metrics"""
        total_return = (1 + returns).prod() - 1
        
        # Excess return
        excess_return = total_return - benchmark_return
        
        # Information ratio (if we had benchmark returns series, we could calculate tracking error)
        # For now, just return basic comparison
        
        return {
            'excess_return': excess_return,
            'benchmark_return': benchmark_return
        }
    
    def _get_empty_metrics(self) -> Dict[str, float]:
        """Return empty metrics dictionary"""
        return {
            'total_return': 0.0,
            'annualized_return': 0.0,
            'avg_daily_return': 0.0,
            'daily_volatility': 0.0,
            'annualized_volatility': 0.0,
            'sharpe_ratio': 0.0,
            'sortino_ratio': 0.0,
            'max_drawdown': 0.0,
            'max_drawdown_duration': 0,
            'calmar_ratio': 0.0,
            'current_drawdown': 0.0,
            'win_rate': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'profit_factor': 0.0,
            'expected_value': 0.0,
            'var_95': 0.0,
            'cvar_95': 0.0,
            'excess_return': 0.0,
            'benchmark_return': 0.0,
            'trading_days': 0,
            'total_trading_days': 0
        }
    
    def format_metrics_report(self, metrics: Dict[str, Any]) -> str:
        """Format metrics into a readable report"""
        report = """
=== Performance Report ===

Return Metrics:
  Total Return:      {total_return:.2%}
  Annualized Return: {annualized_return:.2%}
  Excess Return:     {excess_return:.2%}

Risk Metrics:
  Volatility:        {annualized_volatility:.2%}
  Max Drawdown:      {max_drawdown:.2%}
  VaR (95%):         {var_95:.2%}

Risk-Adjusted Metrics:
  Sharpe Ratio:      {sharpe_ratio:.2f}
  Sortino Ratio:     {sortino_ratio:.2f}
  Calmar Ratio:      {calmar_ratio:.2f}

Trading Metrics:
  Win Rate:          {win_rate:.2%}
  Profit Factor:     {profit_factor:.2f}
  Avg Win:           {avg_win:.2%}
  Avg Loss:          {avg_loss:.2%}

Trading Period:      {trading_days} days
        """.format(**metrics)
        
        return report