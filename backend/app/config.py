"""
Configuration management.
Load configuration uniformly from the project root `.env` file.
"""

import os
from dotenv import load_dotenv

# Load the `.env` file from the project root.
# Path: MiroFish/.env (relative to backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # If the project root does not contain `.env`, fall back to process environment variables.
    load_dotenv(override=True)


class Config:
    """Flask configuration."""
    
    # Flask settings.
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON settings: disable ASCII escaping so UTF-8 is emitted directly instead of \uXXXX.
    JSON_AS_ASCII = False
    
    # LLM settings using the OpenAI-compatible format.
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Zep settings.
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    
    # File upload settings.
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown', 'csv'}
    
    # Text processing settings.
    DEFAULT_CHUNK_SIZE = 500  # Default chunk size.
    DEFAULT_CHUNK_OVERLAP = 50  # Default overlap size.
    
    # OASIS simulation settings.
    SIMULATION_TIMEZONE = os.environ.get('SIMULATION_TIMEZONE', 'UTC')
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    SIMULATION_AGENT_COUNT = int(os.environ.get('SIMULATION_AGENT_COUNT', '15'))
    SIMULATION_PROFILE_PARALLEL_COUNT = int(os.environ.get('SIMULATION_PROFILE_PARALLEL_COUNT', '5'))

    # Available OASIS platform actions.
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Twitter platform weights.
    TWITTER_VIRAL_THRESHOLD = int(os.environ.get('TWITTER_VIRAL_THRESHOLD', '10'))
    TWITTER_ECHO_CHAMBER_STRENGTH = float(os.environ.get('TWITTER_ECHO_CHAMBER_STRENGTH', '0.5'))
    TWITTER_RECENCY_WEIGHT = float(os.environ.get('TWITTER_RECENCY_WEIGHT', '0.4'))
    TWITTER_POPULARITY_WEIGHT = float(os.environ.get('TWITTER_POPULARITY_WEIGHT', '0.3'))
    TWITTER_RELEVANCE_WEIGHT = float(os.environ.get('TWITTER_RELEVANCE_WEIGHT', '0.3'))

    # Reddit platform weights.
    REDDIT_VIRAL_THRESHOLD = int(os.environ.get('REDDIT_VIRAL_THRESHOLD', '15'))
    REDDIT_ECHO_CHAMBER_STRENGTH = float(os.environ.get('REDDIT_ECHO_CHAMBER_STRENGTH', '0.6'))
    REDDIT_RECENCY_WEIGHT = float(os.environ.get('REDDIT_RECENCY_WEIGHT', '0.3'))
    REDDIT_POPULARITY_WEIGHT = float(os.environ.get('REDDIT_POPULARITY_WEIGHT', '0.4'))
    REDDIT_RELEVANCE_WEIGHT = float(os.environ.get('REDDIT_RELEVANCE_WEIGHT', '0.3'))

    # Report agent settings.
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls):
        """Validate required configuration."""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is not configured")
        if not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY is not configured")
        return errors
