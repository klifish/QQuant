"""
Strategy editor for creating and modifying trading strategies
"""

import os
import json
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger

from .base import BaseStrategy, StrategyValidator


class StrategyEditor:
    """Strategy editor for creating and managing strategies"""
    
    def __init__(self, strategies_dir: str = "strategies"):
        """
        Initialize strategy editor
        
        Args:
            strategies_dir: Directory to store strategies
        """
        self.strategies_dir = Path(strategies_dir)
        self.strategies_dir.mkdir(exist_ok=True)
        self.validator = StrategyValidator()
        
        logger.info(f"Strategy editor initialized with directory: {strategies_dir}")
    
    def create_strategy(
        self,
        name: str,
        description: str,
        code: str,
        parameters: Dict[str, Any] = None,
        risk_rules: List[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new strategy
        
        Args:
            name: Strategy name
            description: Strategy description
            code: Strategy Python code
            parameters: Strategy parameters
            risk_rules: Risk management rules
            
        Returns:
            Strategy metadata dictionary
        """
        if parameters is None:
            parameters = {}
        
        if risk_rules is None:
            risk_rules = []
        
        # Validate the strategy code
        validation = self.validator.validate_strategy_code(code)
        
        if not validation["valid"]:
            raise ValueError(f"Invalid strategy code: {validation['errors']}")
        
        # Create strategy metadata
        strategy_data = {
            "name": name,
            "description": description,
            "code": code,
            "parameters": parameters,
            "risk_rules": risk_rules,
            "created_at": pd.Timestamp.now().isoformat(),
            "version": "1.0"
        }
        
        # Save to file
        strategy_file = self.strategies_dir / f"{self._sanitize_filename(name)}.json"
        
        with open(strategy_file, 'w', encoding='utf-8') as f:
            json.dump(strategy_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Created strategy: {name}")
        
        # Log warnings if any
        if validation["warnings"]:
            for warning in validation["warnings"]:
                logger.warning(f"Strategy '{name}': {warning}")
        
        return strategy_data
    
    def load_strategy(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Load strategy by name
        
        Args:
            name: Strategy name
            
        Returns:
            Strategy data dictionary or None if not found
        """
        strategy_file = self.strategies_dir / f"{self._sanitize_filename(name)}.json"
        
        if not strategy_file.exists():
            logger.warning(f"Strategy not found: {name}")
            return None
        
        try:
            with open(strategy_file, 'r', encoding='utf-8') as f:
                strategy_data = json.load(f)
            
            logger.info(f"Loaded strategy: {name}")
            return strategy_data
            
        except Exception as e:
            logger.error(f"Error loading strategy {name}: {e}")
            return None
    
    def update_strategy(
        self,
        name: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update existing strategy
        
        Args:
            name: Strategy name
            updates: Dictionary of updates
            
        Returns:
            Updated strategy data or None if not found
        """
        strategy_data = self.load_strategy(name)
        
        if not strategy_data:
            return None
        
        # Apply updates
        for key, value in updates.items():
            if key in strategy_data:
                strategy_data[key] = value
        
        # Validate code if it was updated
        if "code" in updates:
            validation = self.validator.validate_strategy_code(strategy_data["code"])
            if not validation["valid"]:
                raise ValueError(f"Invalid strategy code: {validation['errors']}")
        
        # Update version and timestamp
        strategy_data["version"] = str(float(strategy_data.get("version", "1.0")) + 0.1)
        strategy_data["updated_at"] = pd.Timestamp.now().isoformat()
        
        # Save updated strategy
        strategy_file = self.strategies_dir / f"{self._sanitize_filename(name)}.json"
        
        with open(strategy_file, 'w', encoding='utf-8') as f:
            json.dump(strategy_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Updated strategy: {name}")
        return strategy_data
    
    def delete_strategy(self, name: str) -> bool:
        """
        Delete strategy
        
        Args:
            name: Strategy name
            
        Returns:
            True if deleted, False if not found
        """
        strategy_file = self.strategies_dir / f"{self._sanitize_filename(name)}.json"
        
        if not strategy_file.exists():
            logger.warning(f"Strategy not found: {name}")
            return False
        
        try:
            strategy_file.unlink()
            logger.info(f"Deleted strategy: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting strategy {name}: {e}")
            return False
    
    def list_strategies(self) -> List[Dict[str, Any]]:
        """
        List all available strategies
        
        Returns:
            List of strategy metadata dictionaries
        """
        strategies = []
        
        for strategy_file in self.strategies_dir.glob("*.json"):
            try:
                with open(strategy_file, 'r', encoding='utf-8') as f:
                    strategy_data = json.load(f)
                
                # Add file info
                strategy_data["file_path"] = str(strategy_file)
                strategies.append(strategy_data)
                
            except Exception as e:
                logger.error(f"Error loading strategy file {strategy_file}: {e}")
                continue
        
        # Sort by creation time
        strategies.sort(key=lambda x: x.get("created_at", ""))
        
        logger.info(f"Found {len(strategies)} strategies")
        return strategies
    
    def duplicate_strategy(self, source_name: str, new_name: str) -> Optional[Dict[str, Any]]:
        """
        Duplicate existing strategy
        
        Args:
            source_name: Source strategy name
            new_name: New strategy name
            
        Returns:
            New strategy data or None if source not found
        """
        source_data = self.load_strategy(source_name)
        
        if not source_data:
            return None
        
        # Create duplicate with new name
        duplicate_data = source_data.copy()
        duplicate_data["name"] = new_name
        duplicate_data["description"] = f"Copy of {source_data['description']}"
        duplicate_data["created_at"] = pd.Timestamp.now().isoformat()
        duplicate_data["version"] = "1.0"
        
        # Remove update timestamp if exists
        if "updated_at" in duplicate_data:
            del duplicate_data["updated_at"]
        
        # Save duplicate
        strategy_file = self.strategies_dir / f"{self._sanitize_filename(new_name)}.json"
        
        with open(strategy_file, 'w', encoding='utf-8') as f:
            json.dump(duplicate_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Duplicated strategy {source_name} -> {new_name}")
        return duplicate_data
    
    def export_strategy(self, name: str, export_path: str) -> bool:
        """
        Export strategy to file
        
        Args:
            name: Strategy name
            export_path: Export file path
            
        Returns:
            True if exported successfully
        """
        strategy_data = self.load_strategy(name)
        
        if not strategy_data:
            return False
        
        try:
            export_file = Path(export_path)
            export_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(strategy_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Exported strategy {name} to {export_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting strategy {name}: {e}")
            return False
    
    def import_strategy(self, import_path: str, overwrite: bool = False) -> Optional[Dict[str, Any]]:
        """
        Import strategy from file
        
        Args:
            import_path: Import file path
            overwrite: Whether to overwrite existing strategy
            
        Returns:
            Imported strategy data or None if failed
        """
        try:
            import_file = Path(import_path)
            
            if not import_file.exists():
                logger.error(f"Import file not found: {import_path}")
                return None
            
            with open(import_file, 'r', encoding='utf-8') as f:
                strategy_data = json.load(f)
            
            # Validate required fields
            required_fields = ["name", "code"]
            for field in required_fields:
                if field not in strategy_data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Check if strategy already exists
            existing = self.load_strategy(strategy_data["name"])
            if existing and not overwrite:
                raise ValueError(f"Strategy '{strategy_data['name']}' already exists")
            
            # Validate strategy code
            validation = self.validator.validate_strategy_code(strategy_data["code"])
            if not validation["valid"]:
                raise ValueError(f"Invalid strategy code: {validation['errors']}")
            
            # Update timestamps
            strategy_data["imported_at"] = pd.Timestamp.now().isoformat()
            
            # Save imported strategy
            strategy_file = self.strategies_dir / f"{self._sanitize_filename(strategy_data['name'])}.json"
            
            with open(strategy_file, 'w', encoding='utf-8') as f:
                json.dump(strategy_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Imported strategy: {strategy_data['name']}")
            return strategy_data
            
        except Exception as e:
            logger.error(f"Error importing strategy: {e}")
            return None
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for cross-platform compatibility"""
        # Replace invalid characters
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Remove leading/trailing spaces and dots
        filename = filename.strip('. ')
        
        # Limit length
        if len(filename) > 100:
            filename = filename[:100]
        
        return filename