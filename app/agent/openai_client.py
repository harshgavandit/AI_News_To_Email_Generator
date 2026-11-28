"""Single gateway for OpenAI calls: task-based model routing, fallback, budgets and usage accounting."""
import os
import time
from functools import lru_cache

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, NotFoundError, OpenAI, PermissionDeniedError, RateLimitError
from pydantic import BaseModel

load_dotenv()

DEFAULT_MODEL = "gpt-6-luna"  # gpt-4o-mini shuts down on 14 Jan 2027.
REQUEST_TIMEOUT_SECONDS = 45
# Each task maps to a cost tier. Cheap, high-volume work uses the fast tier; multi-source
# comparison uses the deep tier. Tiers are configured with NEWS_AI_MODEL_<TIER>.
TASK_TIERS = {
    "watch_draft": "fast", "explain": "fast", "technical_brief": "fast", "curate": "fast", "email_intro": "fast",
    "query_understanding": "fast",
    "search": "standard", "analyze": "standard", "brief": "standard", "visit_catchup": "standard",
    "technology": "standard", "project": "standard", "digest": "standard", "general": "standard",
    "compare": "deep", "global_compare": "deep",
    "deep_plan": "fast", "deep_assess": "fast", "deep_write": "deep",
}


class BudgetExceeded(RuntimeError):
    """The configured daily AI spend ceiling was reached."""


def get_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    return api_key


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def tier_for(task: str) -> str:
    return TASK_TIERS.get(task, "standard")


def route_model(task: str = "general") -> str:
    """Return the configured model for a task's tier, falling back to OPENAI_MODEL."""
    tier = tier_for(task)
    configured = os.getenv(f"NEWS_AI_MODEL_{tier.upper()}")
    if not configured and tier == "deep":
        configured = os.getenv("NEWS_AI_ANALYSIS_MODEL")  # Earlier name for the comparison model.
    return configured or get_openai_model()


REASONING_DEFAULTS = {"fast": "medium", "standard": "medium", "deep": "medium"}
REASONING_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
REASONING_HEADROOM = 2000  # Reasoning tokens count against max_completion_tokens.


def reasoning_effort(model: str, task: str = "general") -> str | None:
    """Reasoning effort for reasoning-capable models; None for models that reject the parameter.

    All tiers default to medium; NEWS_AI_REASONING_<TIER> can override each tier.
    """
    name = model.lower()
    if not (name.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")) and "chat" not in name):
        return None
    tier = tier_for(task)
    value = (os.getenv(f"NEWS_AI_REASONING_{tier.upper()}") or REASONING_DEFAULTS[tier]).strip().lower()
    if value not in REASONING_LEVELS:
        value = REASONING_DEFAULTS[tier]
    if value == "none" and any(family in name for family in ("-sol", "-astra")):
        value = "low"  # The larger GPT-6 models have no "none" setting.
    return value


def fallback_model(primary: str) -> str | None:
    candidate = os.getenv("NEWS_AI_FALLBACK_MODEL", DEFAULT_MODEL)
    return candidate if candidate and candidate != primary else None


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    return OpenAI(api_key=get_openai_api_key(), timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0)


def _record(task, model, usage=None, *, ok=True, store=None):
    from app import ai_usage
    def tokens(name):
        value = getattr(usage, name, 0)
        return value if isinstance(value, int) and value >= 0 else 0

    try:
        ai_usage.record(task, model, tokens("prompt_tokens"), tokens("completion_tokens"), ok=ok, store=store)
    except Exception:
        pass  # Accounting must never fail a model call.


def _fallback_worthy(error) -> bool:
    """Errors where another model may succeed. Authentication and quota errors affect every model."""
    if isinstance(error, (NotFoundError, PermissionDeniedError)):
        return True
    if isinstance(error, RateLimitError):
        body = getattr(error, "body", None)
        code = (body.get("code") or (body.get("error") or {}).get("code")) if isinstance(body, dict) else None
        return code != "insufficient_quota"
    return isinstance(error, APIConnectionError) or (isinstance(error, APIStatusError) and error.status_code >= 500)


def _complete(model, messages, max_tokens, response_model, task="general", *, timeout=None):
    client = get_client()
    completions = (client if timeout is None else client.with_options(timeout=timeout, max_retries=0)).chat.completions
    options = dict(model=model, messages=messages, max_completion_tokens=max_tokens)
    if effort := reasoning_effort(model, task):
        options["reasoning_effort"] = effort
        if effort != "none" and timeout is None:
            options["max_completion_tokens"] = max_tokens + REASONING_HEADROOM
    if response_model:
        completion = completions.parse(**options, response_format=response_model)
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("The model could not produce a valid digest.")
        return parsed.model_dump_json(), completion.usage
    completion = completions.create(**options, response_format={"type": "json_object"})
    return completion.choices[0].message.content or "{}", completion.usage


def generate_bounded_response(prompt, system, schema, *, task, max_tokens, input_bound, timeout, store):
    """One routed provider attempt with an inclusive completion cap and no retry."""
    from app import ai_usage

    if not ai_usage.within_budget():
        raise BudgetExceeded("The daily AI budget was reached.")
    model = route_model(task)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    try:
        content, usage = _complete(model, messages, max_tokens, schema, task, timeout=timeout)
    except Exception as error:
        usage = getattr(getattr(error, "completion", None), "usage", None)
        if usage is None and isinstance(error, APIConnectionError):
            # A timed out call may still have been billed by the provider.
            ai_usage.record(task, model, input_bound, max_tokens, ok=False, store=store)
        else:
            _record(task, model, usage, ok=False, store=store)
        raise
    _record(task, model, usage, store=store)
    return content


def generate_response(prompt: str, system_prompt: str = "Return JSON.", response_model: type[BaseModel] | None = None,
                      *, max_tokens: int = 2400, model: str | None = None, task: str = "general") -> str:
    from app import ai_usage
    if not ai_usage.within_budget():
        raise BudgetExceeded("The daily AI budget was reached.")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt[:24000]},
    ]
    primary = model or route_model(task)
    candidates = [primary, *filter(None, [fallback_model(primary)])]
    last_error = None
    for index, current in enumerate(candidates):
        for attempt in range(2):
            try:
                content, usage = _complete(current, messages, max_tokens, response_model, task)
                _record(task, current, usage)
                return content
            except (APIConnectionError, APIStatusError) as error:
                last_error = error
                _record(task, current, ok=False)
                transient = isinstance(error, APIConnectionError) or error.status_code >= 500
                if attempt or not transient:
                    break
                time.sleep(0.35)
        if index + 1 < len(candidates) and _fallback_worthy(last_error):
            continue
        raise last_error
    raise last_error


def embed_texts(texts, *, model="text-embedding-3-small", dimensions=None, timeout=8):
    from app import ai_usage
    if not ai_usage.within_budget():
        raise BudgetExceeded("The daily AI budget was reached.")
    options = {"dimensions": dimensions} if dimensions else {}
    try:
        result = get_client().with_options(timeout=timeout, max_retries=0).embeddings.create(
            model=model, input=texts, encoding_format="float", **options)
    except Exception:
        _record("embedding", model, ok=False)
        raise
    _record("embedding", model, getattr(result, "usage", None))
    return result
