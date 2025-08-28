"""
Data manager for multi-source A-share market data integration
Supports Tushare Pro and AkShare APIs with intelligent caching
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Union
from loguru import logger
import asyncio
import time

from .cache import DataCache
from .cleaner import DataCleaner


class DataManager:
    """
    Multi-source data manager for A-share market data
    Integrates Tushare Pro and AkShare with intelligent caching
    """
    
    def __init__(self, cache_dir: str = "cache"):
        """
        Initialize data manager
        
        Args:
            cache_dir: Directory for data cache
        """
        self.cache = DataCache(cache_dir)
        self.cleaner = DataCleaner()
        
        # API clients
        self.tushare_client = None
        self.akshare_available = False
        
        self._init_data_sources()
        logger.info("Data manager initialized with multi-source integration")
    
    def _init_data_sources(self):
        """Initialize data source API clients"""
        # Initialize Tushare Pro
        tushare_token = os.getenv("TUSHARE_TOKEN")
        if tushare_token:
            try:
                import tushare as ts
                ts.set_token(tushare_token)
                self.tushare_client = ts.pro_api()
                logger.info("Tushare Pro API initialized")
            except ImportError:
                logger.warning("Tushare not installed, skipping Tushare integration")
            except Exception as e:
                logger.error(f"Failed to initialize Tushare: {e}")
        else:
            logger.warning("TUSHARE_TOKEN not found, Tushare features disabled")
        
        # Check AkShare availability
        try:
            import akshare as ak
            self.akshare_available = True
            logger.info("AkShare API available")
        except ImportError:
            logger.warning("AkShare not installed, skipping AkShare integration")
    
    def get_stock_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        data_type: str = "daily",
        use_cache: bool = True,
        clean_data: bool = True
    ) -> Optional[pd.DataFrame]:
        """
        Get stock data from multiple sources with caching
        
        Args:
            symbol: Stock symbol (e.g., '000001.SZ', '600000.SH')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            data_type: Data frequency ('daily' or 'minute')
            use_cache: Whether to use cached data
            clean_data: Whether to clean the data
            
        Returns:
            DataFrame with OHLCV data or None if failed
        """
        # Try cache first
        if use_cache:
            cached_data = self.cache.get_cached_data(symbol, data_type, start_date, end_date)
            if cached_data is not None:
                return cached_data
        
        # Fetch from data sources
        data = None
        data_source = None
        
        # Try Tushare first (usually more reliable)
        if self.tushare_client and data_type == "daily":
            data, data_source = self._fetch_from_tushare(symbol, start_date, end_date)
        
        # Fallback to AkShare
        if data is None and self.akshare_available:
            data, data_source = self._fetch_from_akshare(symbol, start_date, end_date, data_type)
        
        if data is None:
            logger.error(f"Failed to fetch data for {symbol} from all sources")
            return None
        
        # Clean data if requested
        if clean_data:
            data = self.cleaner.clean_stock_data(data)
        
        # Cache the data
        if use_cache and not data.empty:
            self.cache.cache_data(symbol, data_type, start_date, end_date, data, data_source)
        
        logger.info(f"Retrieved {len(data)} records for {symbol} from {data_source}")
        return data
    
    def _fetch_from_tushare(
        self, 
        symbol: str, 
        start_date: str, 
        end_date: str
    ) -> tuple[Optional[pd.DataFrame], str]:
        """
        Fetch data from Tushare Pro API
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            
        Returns:
            Tuple of (DataFrame, source_name)
        """
        try:
            # Convert symbol format for Tushare
            if '.' in symbol:
                ts_symbol = symbol
            else:
                # Assume it's already in correct format or add default suffix
                ts_symbol = f"{symbol}.SZ" if symbol.startswith('0') or symbol.startswith('3') else f"{symbol}.SH"
            
            # Fetch daily data
            df = self.tushare_client.daily(
                ts_code=ts_symbol,
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', '')
            )
            
            if df.empty:
                return None, "tushare"
            
            # Convert to standard format
            df = df.rename(columns={
                'trade_date': 'date',
                'vol': 'volume'
            })
            
            # Convert date and set as index
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            
            # Select relevant columns
            columns = ['open', 'high', 'low', 'close', 'volume']
            if 'amount' in df.columns:
                columns.append('amount')
            
            df = df[columns]
            
            # Add a small delay to respect API limits
            time.sleep(0.1)
            
            return df, "tushare"
            
        except Exception as e:
            logger.error(f"Tushare fetch failed for {symbol}: {e}")
            return None, "tushare"
    
    def _fetch_from_akshare(
        self, 
        symbol: str, 
        start_date: str, 
        end_date: str,
        data_type: str = "daily"
    ) -> tuple[Optional[pd.DataFrame], str]:
        """
        Fetch data from AkShare API
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            data_type: Data type ('daily' or 'minute')
            
        Returns:
            Tuple of (DataFrame, source_name)
        """
        try:
            import akshare as ak
            
            # Convert symbol format for AkShare
            if '.' in symbol:
                ak_symbol = symbol.replace('.SZ', '').replace('.SH', '')
            else:
                ak_symbol = symbol
            
            # Fetch data based on type
            if data_type == "daily":
                df = ak.stock_zh_a_hist(
                    symbol=ak_symbol,
                    start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', ''),
                    adjust="qfq"  # Forward adjusted
                )
            else:
                # For minute data, use different function
                logger.warning("Minute data from AkShare not implemented yet")
                return None, "akshare"
            
            if df is None or df.empty:
                return None, "akshare"
            
            # Standardize column names
            column_mapping = {
                '日期': 'date',
                '开盘': 'open', 
                '最高': 'high',
                '最低': 'low',
                '收盘': 'close',
                '成交量': 'volume',
                '成交额': 'amount'
            }
            
            df = df.rename(columns=column_mapping)
            
            # Convert date and set as index
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date').sort_index()
            
            # Select relevant columns
            columns = ['open', 'high', 'low', 'close', 'volume']
            if 'amount' in df.columns:
                columns.append('amount')
            
            available_columns = [col for col in columns if col in df.columns]
            df = df[available_columns]
            
            # Add a small delay to respect API limits
            time.sleep(0.2)
            
            return df, "akshare"
            
        except Exception as e:
            logger.error(f"AkShare fetch failed for {symbol}: {e}")
            return None, "akshare"
    
    async def get_multiple_stocks_async(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        data_type: str = "daily",
        use_cache: bool = True,
        clean_data: bool = True
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Asynchronously fetch data for multiple stocks
        
        Args:
            symbols: List of stock symbols
            start_date: Start date
            end_date: End date
            data_type: Data frequency
            use_cache: Whether to use cache
            clean_data: Whether to clean data
            
        Returns:
            Dictionary mapping symbols to DataFrames
        """
        async def fetch_single(symbol: str) -> tuple[str, Optional[pd.DataFrame]]:
            """Fetch data for a single symbol"""
            data = self.get_stock_data(
                symbol, start_date, end_date, data_type, use_cache, clean_data
            )
            return symbol, data
        
        # Create tasks for all symbols
        tasks = [fetch_single(symbol) for symbol in symbols]
        
        # Execute tasks concurrently with some limits to avoid overwhelming APIs
        results = {}
        batch_size = 5  # Process 5 stocks at a time
        
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            batch_results = await asyncio.gather(*batch, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error(f"Async fetch error: {result}")
                else:
                    symbol, data = result
                    results[symbol] = data
            
            # Small delay between batches
            if i + batch_size < len(tasks):
                await asyncio.sleep(1)
        
        logger.info(f"Fetched data for {len([k for k, v in results.items() if v is not None])}/{len(symbols)} symbols")
        return results
    
    def get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get basic stock information
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with stock info or None
        """
        try:
            if self.tushare_client:
                return self._get_stock_info_tushare(symbol)
            elif self.akshare_available:
                return self._get_stock_info_akshare(symbol)
            else:
                logger.error("No data sources available for stock info")
                return None
                
        except Exception as e:
            logger.error(f"Error getting stock info for {symbol}: {e}")
            return None
    
    def _get_stock_info_tushare(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get stock info from Tushare"""
        try:
            ts_symbol = symbol if '.' in symbol else f"{symbol}.SZ"
            
            # Get basic info
            basic_info = self.tushare_client.stock_basic(ts_code=ts_symbol)
            if basic_info.empty:
                return None
            
            info = basic_info.iloc[0].to_dict()
            
            # Get latest market data
            latest_data = self.tushare_client.daily(
                ts_code=ts_symbol,
                start_date=(datetime.now() - timedelta(days=10)).strftime('%Y%m%d'),
                end_date=datetime.now().strftime('%Y%m%d')
            )
            
            if not latest_data.empty:
                latest = latest_data.iloc[0]
                info.update({
                    'latest_price': latest.get('close'),
                    'latest_date': latest.get('trade_date')
                })
            
            return info
            
        except Exception as e:
            logger.error(f"Error getting Tushare stock info: {e}")
            return None
    
    def _get_stock_info_akshare(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get stock info from AkShare"""
        try:
            import akshare as ak
            
            ak_symbol = symbol.replace('.SZ', '').replace('.SH', '') if '.' in symbol else symbol
            
            # Get basic stock info (this is a simplified version)
            info = {
                'ts_code': symbol,
                'symbol': ak_symbol,
                'name': f"Stock_{ak_symbol}",  # AkShare requires different calls for names
                'area': 'China',
                'industry': 'Unknown',
                'market': 'A-share'
            }
            
            return info
            
        except Exception as e:
            logger.error(f"Error getting AkShare stock info: {e}")
            return None
    
    def get_market_calendar(self, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        Get trading calendar for date range
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            DataFrame with trading dates or None
        """
        try:
            if self.tushare_client:
                cal = self.tushare_client.trade_cal(
                    start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', '')
                )
                
                # Filter trading days only
                trading_days = cal[cal['is_open'] == 1]['cal_date']
                trading_days = pd.to_datetime(trading_days)
                
                return pd.DataFrame({'trading_date': trading_days})
            else:
                logger.warning("Trading calendar requires Tushare API")
                return None
                
        except Exception as e:
            logger.error(f"Error getting market calendar: {e}")
            return None
    
    def clear_cache(self, symbol: Optional[str] = None):
        """Clear cached data"""
        self.cache.clear_cache(symbol)
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache information"""
        return self.cache.get_cache_info()
    
    def test_data_sources(self) -> Dict[str, bool]:
        """
        Test connectivity to all data sources
        
        Returns:
            Dictionary with source availability status
        """
        results = {}
        
        # Test Tushare
        try:
            if self.tushare_client:
                # Try a simple API call
                test_data = self.tushare_client.trade_cal(
                    start_date='20240101',
                    end_date='20240102'
                )
                results['tushare'] = not test_data.empty
            else:
                results['tushare'] = False
        except Exception as e:
            logger.error(f"Tushare test failed: {e}")
            results['tushare'] = False
        
        # Test AkShare
        try:
            if self.akshare_available:
                import akshare as ak
                # Try a simple call
                test_data = ak.stock_zh_a_hist(
                    symbol="000001",
                    start_date="20240101",
                    end_date="20240102"
                )
                results['akshare'] = test_data is not None and not test_data.empty
            else:
                results['akshare'] = False
        except Exception as e:
            logger.error(f"AkShare test failed: {e}")
            results['akshare'] = False
        
        logger.info(f"Data source availability: {results}")
        return results