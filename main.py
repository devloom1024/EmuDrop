"""
Main entry point for the Game Downloader application.

This module initializes and runs the main application loop, handling any top-level
exceptions that might occur during execution.
"""
from typing import NoReturn
from app import GameDownloaderApp
from utils.logger import logger
from utils import net
import os
import sys

def main() -> NoReturn:
    """
    Main entry point for the game downloader application.
    
    Initializes the GameDownloaderApp and handles any uncaught exceptions,
    ensuring they are properly logged before the application exits.
    """
    try:
        #load .env file if in development
        if not getattr(sys, 'frozen', False):
            from dotenv import load_dotenv
            load_dotenv()
            logger.info("Environment variables have been loaded successfully from .env file")

        # Load proxy settings (assets/proxy.conf) before any network activity
        net.configure()

        # QA hook: verify the configured path without touching the UI
        if os.environ.get("EMUDROP_DEBUG_TEST") == "1":
            ok, message = net.test_connection()
            logger.info(f"Proxy self-test: {'OK' if ok else 'FAILED'} - {message}")

        app = GameDownloaderApp()
        app.run()
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception as e:
        logger.error(f"Application failed to start: {e}", exc_info=True)
    finally:
        sys.exit(0)

if __name__ == "__main__":
    main()