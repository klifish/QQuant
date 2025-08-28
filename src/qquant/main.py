"""
Main entry point for QQuant application
"""

import sys
import os
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

# Add src to path for development
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


def setup_logging():
    """Setup logging configuration"""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Remove default handler
    logger.remove()
    
    # Add console handler
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )
    
    # Add file handler
    logger.add(
        logs_dir / "qquant.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days"
    )


def load_config():
    """Load configuration from environment files"""
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)
    
    # Load environment variables
    env_file = config_dir / "secrets.env"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info("Loaded configuration from secrets.env")
    else:
        logger.warning("No secrets.env file found, using environment variables only")


def main():
    """Main entry point"""
    try:
        # Setup logging
        setup_logging()
        logger.info("Starting QQuant v0.1.0")
        
        # Load configuration
        load_config()
        
        # Try to start the GUI application
        try:
            from qquant.ui.main_window_simple import QQuantMainWindow
            app = QQuantMainWindow()
            app.run()
        except ImportError as e:
            logger.warning(f"GUI not available: {e}")
            logger.info("QQuant core functionality is available for programmatic use")
            print("QQuant Phase 1 core functionality is ready!")
            print("GUI components require tkinter which is not available in this environment.")
            print("You can still use QQuant programmatically:")
            print("")
            print("from qquant.data import DataManager")
            print("from qquant.strategy import AIStrategyGenerator")
            print("from qquant.backtest import BacktestEngine")
            print("from qquant.risk import RiskRules")
        
    except Exception as e:
        logger.exception(f"Failed to start QQuant: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()