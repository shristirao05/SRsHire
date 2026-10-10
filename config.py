import os
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
#   SRsHire — Configuration File
#   Update the values below before running
# ──────────────────────────────────────────────
# Your Groq API key is loaded from the .env file (not stored here)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Path to Tesseract OCR executable (default Windows install path)
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Path to Poppler bin folder (update version number if different)
POPPLER_PATH = r"C:\poppler\poppler-26.02.0\Library\bin"

# LLM model to use via Groq
LLM_MODEL = "openai/gpt-oss-120b"

# Minimum match percentage to appear in output folder
# Candidates below this % go to Leftover_Candidates.pdf
MIN_MATCH_PERCENTAGE = 20
