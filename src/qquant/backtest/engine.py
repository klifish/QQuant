"""
Simple backtesting engine for single stock strategies
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Callable
from loguru import logger
from datetime import datetime

from .portfolio import Portfolio
from .metrics import PerformanceMetrics


class BacktestEngine:
    """Simple backtesting engine for single stock strategies"""
    
    def __init__(
        self,
        initial_capital: float = 100000,
        commission: float = 0.001,
        slippage: float = 0.001
    ):
        """
        Initialize backtesting engine
        
        Args:
            initial_capital: Initial capital amount
            commission: Commission rate (e.g., 0.001 = 0.1%)
            slippage: Slippage rate (e.g., 0.001 = 0.1%)
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        
        # Initialize portfolio
        self.portfolio = Portfolio(initial_capital)
        self.performance = PerformanceMetrics()
        
        # Results
        self.results = None
        self.trade_log = []
        
        logger.info(f"Backtest engine initialized with capital: {initial_capital}")
    
    def run_backtest(
        self,
        data: pd.DataFrame,
        strategy: Callable,
        symbol: str,
        start_date: str = None,
        end_date: str = None
    ) -> Dict[str, Any]:
        """
        Run backtest with given strategy
        
        Args:
            data: Historical price data
            strategy: Strategy function or class instance
            symbol: Stock symbol
            start_date: Backtest start date (YYYY-MM-DD)
            end_date: Backtest end date (YYYY-MM-DD)
            
        Returns:
            Backtest results dictionary
        """
        logger.info(f"Starting backtest for {symbol}")
        
        # Filter data by date range
        test_data = self._prepare_data(data, start_date, end_date)
        
        if test_data.empty:
            raise ValueError("No data available for backtesting period")
        
        # Reset portfolio and strategy
        self.portfolio.reset(self.initial_capital)
        self.trade_log = []
        
        # Initialize strategy
        if hasattr(strategy, 'initialize'):
            strategy.initialize(test_data)
        
        # Run simulation
        portfolio_values = []
        signals_log = []
        
        for i in range(len(test_data)):
            current_bar = test_data.iloc[i]
            current_date = current_bar['date']
            current_price = current_bar['close']
            
            # Update portfolio value
            self.portfolio.update_value(current_price, current_date)
            portfolio_values.append({
                'date': current_date,
                'portfolio_value': self.portfolio.total_value,
                'cash': self.portfolio.cash,
                'position_value': self.portfolio.position * current_price,
                'position': self.portfolio.position
            })
            
            # Generate signal
            try:
                if hasattr(strategy, 'next_bar'):
                    signal = strategy.next_bar(current_bar, self.portfolio.get_state())
                else:
                    signal = strategy(current_bar, self.portfolio.get_state())
                
                signals_log.append({
                    'date': current_date,
                    'signal': signal,
                    'price': current_price
                })
                
                # Execute trade based on signal
                self._execute_signal(signal, current_price, current_date, strategy)
                
            except Exception as e:
                logger.error(f"Error processing bar {i}: {e}")
                continue
        
        # Calculate final results
        portfolio_df = pd.DataFrame(portfolio_values)
        signals_df = pd.DataFrame(signals_log)
        
        self.results = self._calculate_results(portfolio_df, signals_df, test_data, symbol)
        
        logger.info(f"Backtest completed. Total return: {self.results['total_return']:.2%}")
        return self.results
    
    def _prepare_data(self, data: pd.DataFrame, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """Prepare data for backtesting"""
        df = data.copy()
        
        # Ensure date column is datetime
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        else:
            raise ValueError("Data must contain 'date' column")
        
        # Filter by date range
        if start_date:
            start_date = pd.to_datetime(start_date)
            df = df[df['date'] >= start_date]
        
        if end_date:
            end_date = pd.to_datetime(end_date)
            df = df[df['date'] <= end_date]
        
        # Sort by date
        df = df.sort_values('date').reset_index(drop=True)
        
        logger.info(f"Prepared data: {len(df)} bars from {df['date'].min()} to {df['date'].max()}")
        return df
    
    def _execute_signal(self, signal: str, price: float, date: datetime, strategy):
        """Execute trading signal"""
        if signal == 'buy':
            self._execute_buy(price, date, strategy)
        elif signal == 'sell':
            self._execute_sell(price, date, strategy)
        # 'hold' signal does nothing
    
    def _execute_buy(self, price: float, date: datetime, strategy):
        """Execute buy order"""
        if self.portfolio.position >= 0:  # Can buy when no position or already long
            # Calculate shares to buy (use all available cash)
            transaction_cost = self.commission + self.slippage
            effective_price = price * (1 + transaction_cost)
            
            max_shares = int(self.portfolio.cash / effective_price)
            
            if max_shares > 0:
                shares_to_buy = max_shares
                total_cost = shares_to_buy * effective_price
                
                # Execute trade
                self.portfolio.buy(shares_to_buy, effective_price, date)
                
                # Log trade
                trade_info = {
                    'date': date,
                    'action': 'buy',
                    'shares': shares_to_buy,
                    'price': price,
                    'effective_price': effective_price,
                    'cost': total_cost,
                    'commission': shares_to_buy * price * self.commission,
                    'slippage': shares_to_buy * price * self.slippage
                }
                
                self.trade_log.append(trade_info)
                
                # Notify strategy
                if hasattr(strategy, 'on_trade'):
                    strategy.on_trade(trade_info)
                
                logger.debug(f"BUY: {shares_to_buy} shares at {effective_price:.2f}")
    
    def _execute_sell(self, price: float, date: datetime, strategy):
        """Execute sell order"""
        if self.portfolio.position > 0:  # Can only sell when holding shares
            transaction_cost = self.commission + self.slippage
            effective_price = price * (1 - transaction_cost)
            
            shares_to_sell = self.portfolio.position
            total_proceeds = shares_to_sell * effective_price
            
            # Execute trade
            self.portfolio.sell(shares_to_sell, effective_price, date)
            
            # Log trade
            trade_info = {
                'date': date,
                'action': 'sell',
                'shares': shares_to_sell,
                'price': price,
                'effective_price': effective_price,
                'proceeds': total_proceeds,
                'commission': shares_to_sell * price * self.commission,
                'slippage': shares_to_sell * price * self.slippage
            }
            
            self.trade_log.append(trade_info)
            
            # Notify strategy
            if hasattr(strategy, 'on_trade'):
                strategy.on_trade(trade_info)
            
            logger.debug(f"SELL: {shares_to_sell} shares at {effective_price:.2f}")
    
    def _calculate_results(
        self,
        portfolio_df: pd.DataFrame,
        signals_df: pd.DataFrame,
        price_data: pd.DataFrame,
        symbol: str
    ) -> Dict[str, Any]:
        """Calculate backtest results and performance metrics"""
        
        # Basic performance metrics
        initial_value = portfolio_df['portfolio_value'].iloc[0]
        final_value = portfolio_df['portfolio_value'].iloc[-1]
        total_return = (final_value - initial_value) / initial_value
        
        # Calculate daily returns
        portfolio_df['daily_return'] = portfolio_df['portfolio_value'].pct_change()
        
        # Benchmark (buy and hold)
        price_data_filtered = price_data[price_data['date'].isin(portfolio_df['date'])]
        benchmark_return = (price_data_filtered['close'].iloc[-1] - price_data_filtered['close'].iloc[0]) / price_data_filtered['close'].iloc[0]
        
        # Performance metrics
        metrics = self.performance.calculate_metrics(
            portfolio_df['daily_return'].dropna(),
            portfolio_df['portfolio_value'],
            benchmark_return
        )
        
        # Trading statistics
        trades_df = pd.DataFrame(self.trade_log) if self.trade_log else pd.DataFrame()
        
        if not trades_df.empty:
            buy_trades = trades_df[trades_df['action'] == 'buy']
            sell_trades = trades_df[trades_df['action'] == 'sell']
            
            trading_stats = {
                'total_trades': len(trades_df),
                'buy_trades': len(buy_trades),
                'sell_trades': len(sell_trades),
                'total_commission': trades_df['commission'].sum() if 'commission' in trades_df.columns else 0,
                'total_slippage': trades_df['slippage'].sum() if 'slippage' in trades_df.columns else 0,
            }
        else:
            trading_stats = {
                'total_trades': 0,
                'buy_trades': 0,
                'sell_trades': 0,
                'total_commission': 0,
                'total_slippage': 0,
            }
        
        # Combine all results
        results = {
            'symbol': symbol,
            'start_date': portfolio_df['date'].iloc[0],
            'end_date': portfolio_df['date'].iloc[-1],
            'initial_capital': self.initial_capital,
            'final_value': final_value,
            'total_return': total_return,
            'benchmark_return': benchmark_return,
            'excess_return': total_return - benchmark_return,
            'portfolio_values': portfolio_df,
            'signals': signals_df,
            'trades': trades_df,
            'trading_stats': trading_stats,
            **metrics
        }
        
        return results
    
    def get_results(self) -> Optional[Dict[str, Any]]:
        """Get backtest results"""
        return self.results
    
    def get_trade_log(self) -> list:
        """Get trade log"""
        return self.trade_log.copy()
    
    def reset(self):
        """Reset backtesting engine"""
        self.portfolio.reset(self.initial_capital)
        self.trade_log = []
        self.results = None
        logger.info("Backtest engine reset")