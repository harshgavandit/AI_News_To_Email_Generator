import os
from functools import lru_cache
from openai import OpenAI
from pydantic import BaseModel

from dotenv import load_dotenv


load_dotenv()


def get_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    return api_key


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    return OpenAI(api_key=get_openai_api_key(), timeout=35, max_retries=0)


def generate_response(prompt: str, system_prompt: str = "Return JSON.", response_model: type[BaseModel] | None = None) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt[:24000]},
    ]
    if response_model:
        completion = get_client().chat.completions.parse(
            model=get_openai_model(), messages=messages,
            response_format=response_model, max_completion_tokens=2400,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("The model could not produce a valid digest. Please retry.")
        return parsed.model_dump_json()
    completion = get_client().chat.completions.create(
        model=get_openai_model(), messages=messages,
        response_format={"type": "json_object"}, max_completion_tokens=2400,
    )
    return completion.choices[0].message.content or "{}"
