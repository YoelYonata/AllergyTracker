"""Environment configuration and Pollen API key resolution.

Shared by the ingest, notify, confirm, and api Lambdas so all four read the same env var names.

The Pollen API key is resolved from one of two places so the same code runs locally and in
Lambda without branching on environment (see docs/CONFIGURATION.md):

1. GOOGLE_POLLEN_API_KEY -- plaintext env var, local development only.
2. POLLEN_API_KEY_PARAM  -- name of an SSM Parameter Store SecureString, used on AWS.
"""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv is a local-dev convenience; it isn't bundled into the Lambda package.
    pass

DDB_TABLE_NAME = os.getenv("DDB_TABLE_NAME", "allergy-tracker")
FORECAST_DAYS = int(os.getenv("FORECAST_DAYS", "3"))
READING_TTL_DAYS = int(os.getenv("READING_TTL_DAYS", "365"))
DEFAULT_THRESHOLD = int(os.getenv("DEFAULT_THRESHOLD", "3"))

# Used by the notify and api Lambdas as the SES "From" address -- must be a verified SES identity.
SES_SENDER_EMAIL = os.getenv("SES_SENDER_EMAIL")

# The confirm Lambda's Function URL. POST /subscribe builds the double opt-in link from it, so
# the API function needs to know where the confirm endpoint lives.
CONFIRM_BASE_URL = os.getenv("CONFIRM_BASE_URL")

# Module-level cache so a warm Lambda container calls SSM once, not once per invocation.
_cached_api_key = None


def get_pollen_api_key() -> str:
    global _cached_api_key
    if _cached_api_key:
        return _cached_api_key

    local_key = os.getenv("GOOGLE_POLLEN_API_KEY")
    if local_key:
        _cached_api_key = local_key
        return _cached_api_key

    param_name = os.getenv("POLLEN_API_KEY_PARAM")
    if param_name:
        import boto3

        ssm = boto3.client("ssm")
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
        _cached_api_key = response["Parameter"]["Value"]
        return _cached_api_key

    raise RuntimeError(
        "No Pollen API key configured. Set GOOGLE_POLLEN_API_KEY for local runs, or "
        "POLLEN_API_KEY_PARAM to an SSM SecureString parameter name on AWS. "
        "See docs/CONFIGURATION.md."
    )
