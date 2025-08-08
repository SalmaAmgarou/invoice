import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from a .env file
load_dotenv()

# Get the root directory of the project (the parent of the directory this file is in)
# This makes the paths robust, even if you run the script from a different location.
# If config.py is in 'ai_services', ROOT_DIR will be the parent 'invoice_ocr' folder.
ROOT_DIR = Path(__file__).parent.resolve()

class Settings:
    """
    Holds all the application settings, loaded from environment variables.
    """
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    DATABASE_URL: str = os.getenv("DATABASE_URL")

    # Directories for storing files, now relative to the project root
    UPLOADS_DIR: Path = ROOT_DIR / "uploads"
    REPORTS_DIR: Path = ROOT_DIR / "reports"
    INTERNAL_REPORTS_DIR: Path = ROOT_DIR / "reports_internal"


settings = Settings()

# Create directories if they don't exist
os.makedirs(settings.UPLOADS_DIR, exist_ok=True)
os.makedirs(settings.REPORTS_DIR, exist_ok=True)
os.makedirs(settings.INTERNAL_REPORTS_DIR, exist_ok=True)