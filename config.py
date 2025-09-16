import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@localhost/factures_db")

    # OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    # File Storage
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
    REPORTS_FOLDER = os.getenv("REPORTS_FOLDER", "reports")
    REPORTS_INTERNAL_FOLDER = os.getenv("REPORTS_INTERNAL_FOLDER", "reports_internal")

    # Email (Mailtrap for testing)
    SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "1c01943ecbf425")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "77676f9f6edf65")

    # OCR
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "tesseract")  # Path to tesseract executable

    # Application
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}

    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

    @staticmethod
    def create_folders():
        """Create necessary folders if they don't exist"""
        folders = [Config.UPLOAD_FOLDER, Config.REPORTS_FOLDER, Config.REPORTS_INTERNAL_FOLDER]
        for folder in folders:
            os.makedirs(folder, exist_ok=True)