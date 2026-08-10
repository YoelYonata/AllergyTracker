"""Configuration and secret resolution.

The Pollen API key is resolved from one of two places so the same code runs locally and in
Lambda without branching on environment:

1. GOOGLE_POLLEN_API_KEY  -- plaintext env var, local development only
2. POLLEN_API_KEY_PARAM   -- name of an SSM Parameter Store SecureString, used on AWS

See docs/CONFIGURATION.md for why the key is not a plain Lambda environment variable.
"""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv is a local-dev convenience; it is not bundled into the Lambda package.
    pass

DDB_TABLE_NAME = os.getenv("DDB_TABLE_NAME", "allergy-tracker")
FORECAST_DAYS = int(os.getenv("FORECAST_DAYS", "3"))
READING_TTL_DAYS = int(os.getenv("READING_TTL_DAYS", "365"))

# Cached across warm Lambda invocations so SSM is called once per container, not once per event.
_api_key_cache = None


def get_pollen_api_key() -> str:
    """Return the Google Pollen API key, fetching from SSM on first use if needed."""
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache

    direct = os.getenv("GOOGLE_POLLEN_API_KEY")
    if direct:
        _api_key_cache = direct
        return _api_key_cache

    param_name = os.getenv("POLLEN_API_KEY_PARAM")
    if param_name:
        import boto3

        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
        _api_key_cache = resp["Parameter"]["Value"]
        return _api_key_cache

    raise RuntimeError(
        "No Pollen API key configured. Set GOOGLE_POLLEN_API_KEY for local runs, or "
        "POLLEN_API_KEY_PARAM to an SSM SecureString parameter name on AWS. "
        "See docs/CONFIGURATION.md."
    )
