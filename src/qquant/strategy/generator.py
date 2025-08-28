"""
AI-powered strategy generator
Converts natural language descriptions to Python trading strategies
"""

import os
import re
import json
from typing import Optional, Dict, Any
from loguru import logger
from openai import OpenAI


class AIStrategyGenerator:
    """AI strategy generator using OpenAI API"""
    
    def __init__(self):
        """Initialize the AI strategy generator"""
        self.api_key = os.getenv("OPENAI_API_KEY")
        
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
            logger.info("AI Strategy Generator initialized with OpenAI API")
        else:
            self.client = None
            logger.warning("OpenAI API key not found, AI features will be disabled")
        
        # Load strategy templates and examples
        self.templates = self._load_templates()
    
    def generate_strategy(
        self,
        description: str,
        symbol: str = "000001.SZ",
        initial_capital: float = 100000
    ) -> Optional[Dict[str, Any]]:
        """
        Generate strategy from natural language description
        
        Args:
            description: Natural language strategy description
            symbol: Target stock symbol
            initial_capital: Initial capital amount
            
        Returns:
            Dictionary containing strategy code and metadata
        """
        if not self.client:
            logger.error("OpenAI client not initialized")
            return self._generate_fallback_strategy(description, symbol, initial_capital)
        
        try:
            # Create the prompt
            prompt = self._create_prompt(description, symbol, initial_capital)
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an expert quantitative trading strategy developer. Generate clean, executable Python code for trading strategies."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.3
            )
            
            # Parse response
            strategy_text = response.choices[0].message.content.strip()
            strategy = self._parse_strategy_response(strategy_text, description, symbol, initial_capital)
            
            logger.info(f"Generated strategy: {strategy['name']}")
            return strategy
            
        except Exception as e:
            logger.error(f"Error generating strategy with AI: {e}")
            return self._generate_fallback_strategy(description, symbol, initial_capital)
    
    def _create_prompt(self, description: str, symbol: str, initial_capital: float) -> str:
        """Create prompt for AI strategy generation"""
        
        prompt = f"""
Generate a Python trading strategy based on the following description:

Description: {description}
Target Symbol: {symbol}
Initial Capital: {initial_capital}

Requirements:
1. Create a complete Python class that inherits from BaseStrategy
2. Implement the required methods: initialize, next_bar, on_trade
3. Use pandas for data analysis and technical indicators
4. Include proper risk management (stop loss, position sizing)
5. Add comments explaining the logic
6. Return the strategy as a JSON object with the following structure:

{{
    "name": "strategy_name",
    "description": "brief_description", 
    "code": "complete_python_code",
    "parameters": {{"param1": default_value}},
    "risk_rules": ["rule1", "rule2"]
}}

Base template to follow:

```python
import pandas as pd
import numpy as np
from qquant.strategy.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self, **params):
        super().__init__(**params)
        # Initialize strategy parameters
        
    def initialize(self, data):
        \"\"\"Initialize strategy with historical data\"\"\"
        # Prepare indicators and initial state
        
    def next_bar(self, current_bar, portfolio):
        \"\"\"Process each new bar of data\"\"\"
        # Trading logic here
        # Return signals: 'buy', 'sell', 'hold'
        
    def on_trade(self, trade_info):
        \"\"\"Handle trade execution\"\"\"
        # Log or process trade information
```

Focus on common technical indicators like moving averages, RSI, MACD, etc.
Make the code production-ready and well-commented.
"""
        return prompt
    
    def _parse_strategy_response(
        self,
        response_text: str,
        description: str,
        symbol: str,
        initial_capital: float
    ) -> Dict[str, Any]:
        """Parse AI response into strategy structure"""
        
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                strategy_json = json.loads(json_match.group())
                
                # Validate required fields
                if all(key in strategy_json for key in ['name', 'description', 'code']):
                    return strategy_json
            
            # If JSON parsing fails, extract code manually
            code_match = re.search(r'```python\n(.*?)```', response_text, re.DOTALL)
            if code_match:
                code = code_match.group(1).strip()
                
                return {
                    "name": self._extract_strategy_name(description),
                    "description": description,
                    "code": code,
                    "parameters": {},
                    "risk_rules": ["Stop loss at 5%", "Maximum position 20%"]
                }
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
        
        # Fallback: return the whole response as code
        return {
            "name": self._extract_strategy_name(description),
            "description": description,
            "code": response_text,
            "parameters": {},
            "risk_rules": []
        }
    
    def _extract_strategy_name(self, description: str) -> str:
        """Extract strategy name from description"""
        # Simple heuristic to create strategy name
        words = description.lower().split()
        name_words = []
        
        for word in words[:5]:  # Take first 5 words
            if word.isalpha() and len(word) > 2:
                name_words.append(word.capitalize())
        
        if not name_words:
            return "Custom Strategy"
        
        return " ".join(name_words) + " Strategy"
    
    def _generate_fallback_strategy(
        self,
        description: str,
        symbol: str,
        initial_capital: float
    ) -> Dict[str, Any]:
        """Generate a fallback strategy when AI is not available"""
        
        # Simple moving average crossover strategy as fallback
        strategy_code = f'''import pandas as pd
import numpy as np
from qquant.strategy.base import BaseStrategy

class FallbackStrategy(BaseStrategy):
    """
    Fallback strategy: Simple Moving Average Crossover
    Generated for: {description}
    """
    
    def __init__(self, short_period=5, long_period=20, **params):
        super().__init__(**params)
        self.short_period = short_period
        self.long_period = long_period
        self.position = 0
        
    def initialize(self, data):
        """Initialize with historical data"""
        self.data = data.copy()
        self.data['MA_short'] = self.data['close'].rolling(self.short_period).mean()
        self.data['MA_long'] = self.data['close'].rolling(self.long_period).mean()
        
    def next_bar(self, current_bar, portfolio):
        """Process each bar"""
        if len(self.data) < self.long_period:
            return 'hold'
        
        current_short_ma = self.data['MA_short'].iloc[-1]
        current_long_ma = self.data['MA_long'].iloc[-1]
        prev_short_ma = self.data['MA_short'].iloc[-2]
        prev_long_ma = self.data['MA_long'].iloc[-2]
        
        # Golden cross: short MA crosses above long MA
        if prev_short_ma <= prev_long_ma and current_short_ma > current_long_ma:
            if self.position <= 0:
                return 'buy'
        
        # Death cross: short MA crosses below long MA  
        elif prev_short_ma >= prev_long_ma and current_short_ma < current_long_ma:
            if self.position > 0:
                return 'sell'
        
        return 'hold'
        
    def on_trade(self, trade_info):
        """Handle trade execution"""
        if trade_info['action'] == 'buy':
            self.position = 1
        elif trade_info['action'] == 'sell':
            self.position = -1
'''
        
        return {
            "name": "Fallback MA Crossover Strategy",
            "description": f"Simple moving average crossover strategy (fallback for: {description})",
            "code": strategy_code,
            "parameters": {
                "short_period": 5,
                "long_period": 20
            },
            "risk_rules": [
                "Stop loss at 5%",
                "Position size limited to 50% of capital"
            ]
        }
    
    def _load_templates(self) -> Dict[str, str]:
        """Load pre-defined strategy templates"""
        templates = {
            "moving_average": """
# Moving Average Strategy Template
def moving_average_strategy(data, short_period=5, long_period=20):
    data['MA_short'] = data['close'].rolling(short_period).mean()
    data['MA_long'] = data['close'].rolling(long_period).mean()
    
    signals = []
    for i in range(1, len(data)):
        if (data['MA_short'].iloc[i-1] <= data['MA_long'].iloc[i-1] and 
            data['MA_short'].iloc[i] > data['MA_long'].iloc[i]):
            signals.append('buy')
        elif (data['MA_short'].iloc[i-1] >= data['MA_long'].iloc[i-1] and 
              data['MA_short'].iloc[i] < data['MA_long'].iloc[i]):
            signals.append('sell')
        else:
            signals.append('hold')
    
    return signals
""",
            
            "rsi": """
# RSI Strategy Template
def rsi_strategy(data, rsi_period=14, oversold=30, overbought=70):
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    
    signals = []
    for i in range(len(data)):
        if data['RSI'].iloc[i] < oversold:
            signals.append('buy')
        elif data['RSI'].iloc[i] > overbought:
            signals.append('sell')
        else:
            signals.append('hold')
    
    return signals
"""
        }
        
        return templates
    
    def get_strategy_examples(self) -> Dict[str, str]:
        """Get example strategy descriptions"""
        examples = {
            "Moving Average Crossover": "5日均线上穿20日均线买入，下穿卖出",
            "RSI Mean Reversion": "RSI低于30买入，高于70卖出",
            "Bollinger Bands": "价格跌破下轨买入，突破上轨卖出",
            "MACD Strategy": "MACD金叉买入，死叉卖出",
            "Volume Breakout": "成交量放大配合价格突破时买入"
        }
        
        return examples