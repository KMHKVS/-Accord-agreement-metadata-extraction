import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 120_000
MAX_IMAGES = 40
MAX_PAGES = 30
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
PROVIDERS = {
    'openai': {'label': 'OpenAI', 'key_env': 'OPENAI_API_KEY',
               'model': os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
               'base_url': 'https://api.openai.com/v1'},
    'groq': {'label': 'Groq', 'key_env': 'GROQ_API_KEY',
             'model': os.getenv('GROQ_MODEL', 'qwen/qwen3.8-27b'),
             'base_url': 'https://api.groq.com/openai/v1'},
}
DEFAULT_PROVIDER = os.getenv('AI_PROVIDER', 'openai').strip().lower()
if DEFAULT_PROVIDER not in PROVIDERS:
    raise ValueError('AI_PROVIDER must be openai or groq.')
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER]['model']


def server_key(provider: str = DEFAULT_PROVIDER) -> str:
    return os.getenv(PROVIDERS[provider]['key_env'], '').strip()
