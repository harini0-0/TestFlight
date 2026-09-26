
from __future__ import annotations

import argparse
import os
import sys

DEFAULT_BASE_URL = "https://api.sciforium.com/v1"
DEFAULT_MODEL = "/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash"


def mask(key: str) -> str:
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]} (len={len(key)})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("SCIFORIUM_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.environ.get("SCIFORIUM_DEEPSEEK_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    key = os.environ.get("SCIFORIUM_API_KEY")
    if not key:
        print("SCIFORIUM_API_KEY is not set. export it, or put it in a .env file next to this script.")
        sys.exit(1)

    print(f"Base URL : {args.base_url}")
    print(f"Model    : {args.model}")
    print(f"Key      : {mask(key)}")
    print()

    try:
        from openai import OpenAI
    except ImportError:
        print("Missing dependency: pip install openai")
        sys.exit(1)

    client = OpenAI(base_url="https://api.sciforium.com/v1", api_key=key)

    try:
        response = client.chat.completions.create(
            model="/deployments/506a9a37/deepseek-ai/DeepSeek-V4.1-Flash",
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=10,
        )
        print("SUCCESS:", response.choices[0].message.content)
    except Exception as e:
        print(f"FAILED: {type(e).__name__}")
        print(str(e))
        # print()
        # print("Troubleshooting per Sciforium's docs:")
        # print("  - 404               -> base URL should stop at /v1 (the client adds /chat/completions)")
        # print("  - 'model not found' -> --model must match the model string exactly")
        # print("  - 401 'Invalid or missing API key' regardless of model/URL tried")
        # print("    -> this is the failure mode reported to staff; likely a key-provisioning issue on their side")
        sys.exit(1)


if __name__ == "__main__":
    main()
