import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    API_KEY = [s.strip() for s in os.getenv("API_KEY", "").split(",") if s.strip()]
    ALLOWED_ORIGINS = [s.strip() for s in os.getenv("ALLOWED_ORIGINS", "").split(",") if s.strip()] # A modifier et ajouter URL du frontend

    # File Storage
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
    REPORTS_FOLDER = os.getenv("REPORTS_FOLDER", "reports")
    REPORTS_INTERNAL_FOLDER = os.getenv("REPORTS_INTERNAL_FOLDER", "reports_internal")
    # OCR
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "tesseract")  # Path to tesseract executable

    # Application
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

    @staticmethod
    def create_folders():
        """Create necessary folders if they don't exist"""
        folders = [Config.UPLOAD_FOLDER, Config.REPORTS_FOLDER, Config.REPORTS_INTERNAL_FOLDER]
        for folder in folders:
            os.makedirs(folder, exist_ok=True)

    # Celery / Queue
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    CELERY_RESULT_EXPIRES = int(os.getenv("CELERY_RESULT_EXPIRES", "86400"))  # 24h
    CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "600"))  # 10 min
    CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "540"))
