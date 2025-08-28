"""
Data caching system using SQLite for intelligent caching with freshness management
"""

import sqlite3
import pandas as pd
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from loguru import logger


class DataCache:
    """SQLite-based intelligent caching system for market data"""
    
    def __init__(self, cache_dir: str = "cache"):
        """
        Initialize data cache
        
        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        self.db_path = self.cache_dir / "market_data.db"
        self._init_database()
        
        logger.info(f"Data cache initialized: {self.db_path}")
    
    def _init_database(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create cache metadata table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_metadata (
                cache_key TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                data_type TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                data_source TEXT NOT NULL
            )
        """)
        
        # Create daily data table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_data (
                cache_key TEXT,
                trade_date TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                amount REAL,
                PRIMARY KEY (cache_key, trade_date)
            )
        """)
        
        # Create minute data table  
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS minute_data (
                cache_key TEXT,
                datetime TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                amount REAL,
                PRIMARY KEY (cache_key, datetime)
            )
        """)
        
        conn.commit()
        conn.close()
        
        logger.debug("Cache database tables initialized")
    
    def _generate_cache_key(self, symbol: str, data_type: str, start_date: str, end_date: str) -> str:
        """Generate unique cache key for data request"""
        return f"{symbol}_{data_type}_{start_date}_{end_date}"
    
    def get_cached_data(
        self,
        symbol: str,
        data_type: str,
        start_date: str,
        end_date: str,
        max_age_hours: int = 24
    ) -> Optional[pd.DataFrame]:
        """
        Retrieve cached data if fresh enough
        
        Args:
            symbol: Stock symbol
            data_type: Type of data ('daily' or 'minute')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_age_hours: Maximum age in hours before considering stale
            
        Returns:
            Cached DataFrame if available and fresh, None otherwise
        """
        cache_key = self._generate_cache_key(symbol, data_type, start_date, end_date)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if cached data exists and is fresh
        cursor.execute("""
            SELECT created_at, updated_at, data_source
            FROM cache_metadata 
            WHERE cache_key = ?
        """, (cache_key,))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return None
        
        created_at, updated_at, data_source = result
        update_time = datetime.fromisoformat(updated_at)
        
        # Check if data is still fresh
        if datetime.now() - update_time > timedelta(hours=max_age_hours):
            logger.debug(f"Cache expired for {cache_key}")
            conn.close()
            return None
        
        # Retrieve actual data
        table_name = f"{data_type}_data"
        query = f"""
            SELECT * FROM {table_name}
            WHERE cache_key = ?
            ORDER BY {"trade_date" if data_type == "daily" else "datetime"}
        """
        
        try:
            df = pd.read_sql_query(query, conn, params=(cache_key,))
            conn.close()
            
            if df.empty:
                return None
            
            # Remove cache_key column and set proper index
            df = df.drop('cache_key', axis=1)
            date_col = 'trade_date' if data_type == 'daily' else 'datetime'
            df[date_col] = pd.to_datetime(df[date_col])
            df.set_index(date_col, inplace=True)
            
            logger.info(f"Retrieved cached data for {symbol}: {len(df)} records from {data_source}")
            return df
            
        except Exception as e:
            logger.error(f"Error retrieving cached data: {e}")
            conn.close()
            return None
    
    def cache_data(
        self,
        symbol: str,
        data_type: str,
        start_date: str,
        end_date: str,
        data: pd.DataFrame,
        data_source: str
    ):
        """
        Cache data in SQLite database
        
        Args:
            symbol: Stock symbol
            data_type: Type of data ('daily' or 'minute')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            data: DataFrame to cache
            data_source: Source of the data (e.g., 'tushare', 'akshare')
        """
        if data.empty:
            return
        
        cache_key = self._generate_cache_key(symbol, data_type, start_date, end_date)
        now = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Insert or update metadata
            cursor.execute("""
                INSERT OR REPLACE INTO cache_metadata
                (cache_key, symbol, data_type, start_date, end_date, created_at, updated_at, data_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (cache_key, symbol, data_type, start_date, end_date, now, now, data_source))
            
            # Prepare data for caching
            cache_df = data.copy()
            cache_df['cache_key'] = cache_key
            
            # Reset index to make date/datetime a column with correct name
            date_col_name = 'trade_date' if data_type == 'daily' else 'datetime'
            cache_df.reset_index(inplace=True)
            
            # Rename the index column to match the expected database column
            if cache_df.columns[0] in ['index', 'date']:
                cache_df.rename(columns={cache_df.columns[0]: date_col_name}, inplace=True)
            
            # Insert data into appropriate table
            table_name = f"{data_type}_data"
            
            # Clear existing data for this cache key
            cursor.execute(f"DELETE FROM {table_name} WHERE cache_key = ?", (cache_key,))
            
            # Insert new data
            cache_df.to_sql(table_name, conn, if_exists='append', index=False, method='multi')
            
            conn.commit()
            logger.info(f"Cached {len(data)} records for {symbol} ({data_type}) from {data_source}")
            
        except Exception as e:
            logger.error(f"Error caching data: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def clear_cache(self, symbol: Optional[str] = None, data_type: Optional[str] = None):
        """
        Clear cached data
        
        Args:
            symbol: If provided, clear only data for this symbol
            data_type: If provided, clear only this type of data
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            if symbol and data_type:
                # Clear specific symbol and data type
                cursor.execute("""
                    SELECT cache_key FROM cache_metadata 
                    WHERE symbol = ? AND data_type = ?
                """, (symbol, data_type))
                cache_keys = [row[0] for row in cursor.fetchall()]
                
                for cache_key in cache_keys:
                    cursor.execute("DELETE FROM cache_metadata WHERE cache_key = ?", (cache_key,))
                    cursor.execute(f"DELETE FROM {data_type}_data WHERE cache_key = ?", (cache_key,))
                    
                logger.info(f"Cleared cache for {symbol} ({data_type})")
                
            elif symbol:
                # Clear all data for symbol
                cursor.execute("SELECT cache_key, data_type FROM cache_metadata WHERE symbol = ?", (symbol,))
                results = cursor.fetchall()
                
                for cache_key, dtype in results:
                    cursor.execute("DELETE FROM cache_metadata WHERE cache_key = ?", (cache_key,))
                    cursor.execute(f"DELETE FROM {dtype}_data WHERE cache_key = ?", (cache_key,))
                    
                logger.info(f"Cleared all cache for {symbol}")
                
            else:
                # Clear all cache
                cursor.execute("DELETE FROM cache_metadata")
                cursor.execute("DELETE FROM daily_data")
                cursor.execute("DELETE FROM minute_data")
                logger.info("Cleared all cache")
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache statistics and information"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get metadata count
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        total_entries = cursor.fetchone()[0]
        
        # Get data counts
        cursor.execute("SELECT COUNT(*) FROM daily_data")
        daily_records = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM minute_data")
        minute_records = cursor.fetchone()[0]
        
        # Get recent entries
        cursor.execute("""
            SELECT symbol, data_type, data_source, updated_at
            FROM cache_metadata 
            ORDER BY updated_at DESC 
            LIMIT 5
        """)
        recent_entries = cursor.fetchall()
        
        conn.close()
        
        return {
            'total_entries': total_entries,
            'daily_records': daily_records,
            'minute_records': minute_records,
            'recent_entries': recent_entries,
            'cache_size_mb': self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0
        }