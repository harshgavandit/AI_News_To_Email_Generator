import os
import time
from functools import lru_cache
from openai import APIConnectionError, APIStatusError, OpenAI
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
    return OpenAI(api_key=get_openai_api_key(), timeout=12, max_retries=0)


def generate_response(prompt: str, system_prompt: str = "Return JSON.", response_model: type[BaseModel] | None = None,
                      *, max_tokens: int = 2400) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt[:24000]},
    ]
    completions = get_client().chat.completions
    started = time.monotonic()
    for attempt in range(2):
        try:
            options = dict(model=get_openai_model(), messages=messages, max_completion_tokens=max_tokens)
            if response_model:
                completion = completions.parse(**options, response_format=response_model)
                parsed = completion.choices[0].message.parsed
                if parsed is None:
                    raise ValueError("The model could not produce a valid digest.")
                return parsed.model_dump_json()
            completion = completions.create(**options, response_format={"type": "json_object"})
            return completion.choices[0].message.content or "{}"
        except (APIConnectionError, APIStatusError) as error:
            if (attempt or time.monotonic() - started > 3 or
                    isinstance(error, APIStatusError) and error.status_code < 500):
                raise
            time.sleep(0.35)
