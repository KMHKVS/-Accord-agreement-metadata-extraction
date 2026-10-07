"""Tests must never depend on, or accidentally use, local live credentials."""
import os

os.environ.update({
    'AI_PROVIDER': 'openai',
    'OPENAI_API_KEY': '',
    'GROQ_API_KEY': '',
    'OPENAI_MODEL': 'gpt-4.1-mini',
    'GROQ_MODEL': 'qwen/qwen3.8-27b',
})
