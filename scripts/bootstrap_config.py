"""Import only model configuration from an existing local dotenv file."""

import argparse
from pathlib import Path

from dotenv import dotenv_values, set_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-env", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    if target.exists():
        parser.error("The project .env already exists; refusing to overwrite it.")
    source = dotenv_values(args.from_env)
    if not source.get("OPENAI_API_KEY") or not source.get("OPENAI_BASE_URL"):
        parser.error("Source must contain OPENAI_API_KEY and OPENAI_BASE_URL.")
    model = source.get("SMART_LLM") or "openai:glm-4.7-flash"
    provider, separator, name = model.partition(":")
    if separator and provider != "openai":
        parser.error("This importer only supports OpenAI-compatible model configuration.")
    settings = {
        "OPENAI_API_KEY": source["OPENAI_API_KEY"],
        "OPENAI_BASE_URL": source["OPENAI_BASE_URL"],
        "MODEL_NAME": name if separator else model,
        "REQUEST_TIMEOUT": "60",
    }
    if "glm-4.7-flash" in settings["MODEL_NAME"].lower():
        settings["LLM_EXTRA_BODY"] = '{"thinking":{"type":"disabled"}}'
    target.touch(exist_ok=False)
    for key, value in settings.items():
        set_key(target, key, value, quote_mode="always")
    print("Created an independent project .env. Credentials were not displayed.")


if __name__ == "__main__":
    main()
