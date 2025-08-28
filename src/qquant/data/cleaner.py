"""
Data cleaning and preprocessing utilities for A-share market data
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Tuple
from loguru import logger


class DataCleaner:
    """Data cleaning and preprocessing for market data"""
    
    def __init__(self):
        """Initialize data cleaner"""
        logger.info("Data cleaner initialized")
    
    def clean_stock_data(
        self,
        data: pd.DataFrame,
        fill_method: str = "forward",
        remove_zero_volume: bool = True,
        adjust_splits: bool = True
    ) -> pd.DataFrame:
        """
        Clean stock market data
        
        Args:
            data: Raw stock data DataFrame
            fill_method: Method to fill missing values ('forward', 'backward', 'interpolate', 'drop')
            remove_zero_volume: Remove rows with zero volume
            adjust_splits: Adjust for stock splits
            
        Returns:
            Cleaned DataFrame
        """
        if data.empty:
            return data
        
        cleaned_data = data.copy()
        original_length = len(cleaned_data)
        
        # Ensure proper data types
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']
        if 'amount' in cleaned_data.columns:
            numeric_columns.append('amount')
        
        for col in numeric_columns:
            if col in cleaned_data.columns:
                cleaned_data[col] = pd.to_numeric(cleaned_data[col], errors='coerce')
        
        # Remove rows where all OHLC values are missing
        ohlc_cols = ['open', 'high', 'low', 'close']
        available_ohlc = [col for col in ohlc_cols if col in cleaned_data.columns]
        
        if available_ohlc:
            cleaned_data = cleaned_data.dropna(subset=available_ohlc, how='all')
        
        # Remove zero volume if requested
        if remove_zero_volume and 'volume' in cleaned_data.columns:
            zero_volume_mask = (cleaned_data['volume'] == 0) | (cleaned_data['volume'].isna())
            cleaned_data = cleaned_data[~zero_volume_mask]
        
        # Handle missing values
        if fill_method == "forward":
            cleaned_data = cleaned_data.ffill()
        elif fill_method == "backward":
            cleaned_data = cleaned_data.bfill()
        elif fill_method == "interpolate":
            cleaned_data = cleaned_data.interpolate(method='linear')
        elif fill_method == "drop":
            cleaned_data = cleaned_data.dropna()
        
        # Validate OHLC relationships
        cleaned_data = self._validate_ohlc(cleaned_data)
        
        # Detect and handle stock splits if requested
        if adjust_splits and 'close' in cleaned_data.columns:
            cleaned_data = self._detect_and_adjust_splits(cleaned_data)
        
        # Remove any remaining invalid data
        cleaned_data = self._remove_invalid_data(cleaned_data)
        
        logger.info(f"Data cleaning completed: {original_length} -> {len(cleaned_data)} records")
        return cleaned_data
    
    def _validate_ohlc(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Validate and fix OHLC price relationships
        
        Args:
            data: DataFrame with OHLC data
            
        Returns:
            DataFrame with corrected OHLC relationships
        """
        if not all(col in data.columns for col in ['open', 'high', 'low', 'close']):
            return data
        
        # Fix cases where high < low
        invalid_hl = data['high'] < data['low']
        if invalid_hl.any():
            logger.warning(f"Found {invalid_hl.sum()} records with high < low, swapping values")
            data.loc[invalid_hl, ['high', 'low']] = data.loc[invalid_hl, ['low', 'high']].values
        
        # Fix cases where prices are outside high-low range
        data['open'] = data[['open', 'high']].min(axis=1)
        data['open'] = data[['open', 'low']].max(axis=1)
        
        data['close'] = data[['close', 'high']].min(axis=1)
        data['close'] = data[['close', 'low']].max(axis=1)
        
        return data
    
    def _detect_and_adjust_splits(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Detect stock splits and adjust historical data
        
        Args:
            data: DataFrame with price data
            
        Returns:
            DataFrame with split-adjusted data
        """
        if 'close' not in data.columns or len(data) < 2:
            return data
        
        # Calculate price change ratios
        data_sorted = data.sort_index()
        price_ratios = data_sorted['close'].pct_change().abs()
        
        # Detect potential splits (price changes > 25%)
        split_threshold = 0.25
        potential_splits = price_ratios > split_threshold
        
        if not potential_splits.any():
            return data
        
        logger.info(f"Detected {potential_splits.sum()} potential stock splits")
        
        # For each potential split, determine split ratio and adjust
        adjusted_data = data_sorted.copy()
        
        for split_date in data_sorted[potential_splits].index:
            split_idx = data_sorted.index.get_loc(split_date)
            
            if split_idx > 0:
                before_price = data_sorted['close'].iloc[split_idx - 1]
                after_price = data_sorted['close'].iloc[split_idx]
                
                # Determine split ratio
                ratio = before_price / after_price
                
                # Only adjust if ratio suggests a clear split (2:1, 3:1, etc.)
                if 1.8 <= ratio <= 2.2:  # 2:1 split
                    split_ratio = 2.0
                elif 2.8 <= ratio <= 3.2:  # 3:1 split
                    split_ratio = 3.0
                elif 0.45 <= ratio <= 0.55:  # 1:2 reverse split
                    split_ratio = 0.5
                else:
                    continue  # Skip if not a clear split pattern
                
                # Adjust all prices before the split
                price_cols = ['open', 'high', 'low', 'close']
                for col in price_cols:
                    if col in adjusted_data.columns:
                        adjusted_data.loc[:split_date, col] /= split_ratio
                
                # Adjust volume after the split
                if 'volume' in adjusted_data.columns:
                    adjusted_data.loc[split_date:, 'volume'] *= split_ratio
                
                logger.debug(f"Applied {split_ratio:.1f}:1 split adjustment at {split_date}")
        
        return adjusted_data
    
    def _remove_invalid_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Remove clearly invalid data points
        
        Args:
            data: DataFrame to clean
            
        Returns:
            DataFrame with invalid data removed
        """
        original_len = len(data)
        
        # Remove rows with negative prices
        price_cols = ['open', 'high', 'low', 'close']
        for col in price_cols:
            if col in data.columns:
                data = data[data[col] > 0]
        
        # Remove rows with negative volume
        if 'volume' in data.columns:
            data = data[data['volume'] >= 0]
        
        # Remove extreme outliers (prices that changed more than 50% in one day without volume)
        if 'close' in data.columns and len(data) > 1:
            pct_change = data['close'].pct_change().abs()
            extreme_changes = pct_change > 0.5
            
            if 'volume' in data.columns:
                # Only remove extreme changes with very low volume
                low_volume = data['volume'] < data['volume'].median() * 0.1
                remove_mask = extreme_changes & low_volume
            else:
                # If no volume data, be more conservative
                remove_mask = pct_change > 0.8
            
            if remove_mask.any():
                data = data[~remove_mask]
                logger.warning(f"Removed {remove_mask.sum()} extreme outliers")
        
        logger.debug(f"Invalid data removal: {original_len} -> {len(data)} records")
        return data
    
    def add_technical_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Add common technical indicators to stock data
        
        Args:
            data: OHLC stock data
            
        Returns:
            DataFrame with technical indicators added
        """
        if 'close' not in data.columns:
            return data
        
        result = data.copy()
        close_prices = result['close']
        
        # Moving averages
        result['ma5'] = close_prices.rolling(window=5).mean()
        result['ma10'] = close_prices.rolling(window=10).mean()
        result['ma20'] = close_prices.rolling(window=20).mean()
        result['ma60'] = close_prices.rolling(window=60).mean()
        
        # Relative Strength Index (RSI)
        result['rsi'] = self._calculate_rsi(close_prices, period=14)
        
        # MACD
        macd_line, macd_signal, macd_hist = self._calculate_macd(close_prices)
        result['macd'] = macd_line
        result['macd_signal'] = macd_signal
        result['macd_hist'] = macd_hist
        
        # Bollinger Bands
        if len(result) >= 20:
            bb_middle = close_prices.rolling(window=20).mean()
            bb_std = close_prices.rolling(window=20).std()
            result['bb_upper'] = bb_middle + (bb_std * 2)
            result['bb_middle'] = bb_middle
            result['bb_lower'] = bb_middle - (bb_std * 2)
        
        logger.info("Added technical indicators to data")
        return result
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_macd(
        self, 
        prices: pd.Series, 
        fast_period: int = 12, 
        slow_period: int = 26, 
        signal_period: int = 9
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD indicators"""
        ema_fast = prices.ewm(span=fast_period).mean()
        ema_slow = prices.ewm(span=slow_period).mean()
        
        macd_line = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=signal_period).mean()
        macd_hist = macd_line - macd_signal
        
        return macd_line, macd_signal, macd_hist
    
    def detect_trading_halts(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Detect and mark trading halts/suspensions
        
        Args:
            data: Stock data DataFrame
            
        Returns:
            DataFrame with 'trading_halt' column added
        """
        if 'volume' not in data.columns:
            return data
        
        result = data.copy()
        
        # Mark days with zero volume as potential halts
        result['trading_halt'] = result['volume'] == 0
        
        # Also check for days where price didn't change and volume is very low
        if 'close' in result.columns and len(result) > 1:
            no_price_change = result['close'].diff() == 0
            low_volume = result['volume'] < result['volume'].median() * 0.01
            
            result['trading_halt'] = result['trading_halt'] | (no_price_change & low_volume)
        
        halt_count = result['trading_halt'].sum()
        if halt_count > 0:
            logger.info(f"Detected {halt_count} potential trading halts")
        
        return result