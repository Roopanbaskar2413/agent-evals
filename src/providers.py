"""Model-provider abstraction: one interface, three backends.

agent.py and baseline_sql.py keep the exact same SYSTEM prompt, TOOLS list,
and Pydantic response schemas (FinalAnswer, Query) regardless of which
provider is selected. Each Provider subclass is responsible for translating
those into its own API's shape and translating the response back into the
same dict shape ollama.chat() already returns -- so the calling code's
message-list bookkeeping and tool-call parsing never change.

Gemini and OpenAI providers use raw HTTP (urllib) -- no new dependencies.
Pricing constants are the cheapest/fastest tier of each provider as of this
writing; VERIFY against each provider's current pricing page before
trusting the cost numbers in a real run -- prices change.

API keys are read from GEMINI_API_KEY / OPENAI_API_KEY (environment only)
and used solely to build a request header. Never logged, never printed.
"""

import json
import os
import time
import urllib.error
import urllib.request

USER_AGENT = "agent-evals/0.1"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2
MAX_RATE_LIMIT_RETRIES = 20
RATE_LIMIT_FALLBACK_SECONDS = 15


class Provider:
    """response_schema is a Pydantic model class (FinalAnswer or Query) --
    passed instead of tools for the one-shot/structured-output call sites.
    tools is the OpenAI-style function-list already defined in agent.py."""

    PRICE_IN_PER_1K = 0.0
    PRICE_OUT_PER_1K = 0.0

    def chat(self, messages, tools=None, response_schema=None, temperature=0):
        raise NotImplementedError

    def _cost(self, tokens_in, tokens_out):
        return (tokens_in / 1000) * self.PRICE_IN_PER_1K + (tokens_out / 1000) * self.PRICE_OUT_PER_1K


class OllamaProvider(Provider):
    """Zero behavior change from the original hardcoded ollama.chat() calls
    -- local, free, and the default when --model isn't passed."""

    PRICE_IN_PER_1K = 0.0
    PRICE_OUT_PER_1K = 0.0

    def __init__(self, model_name="llama3.2"):
        self.model_name = model_name

    def chat(self, messages, tools=None, response_schema=None, temperature=0):
        import ollama

        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "options": {"temperature": temperature},
        }
        if tools is not None:
            kwargs["tools"] = tools
        if response_schema is not None:
            kwargs["format"] = response_schema.model_json_schema()

        response = ollama.chat(**kwargs)
        tokens_in = response["prompt_eval_count"]
        tokens_out = response["eval_count"]
        return {
            "message": response["message"],
            "prompt_eval_count": tokens_in,
            "eval_count": tokens_out,
            "cost_usd": self._cost(tokens_in, tokens_out),
        }


def _parse_retry_delay(error, body_text):
    """Prefers the server's own stated delay (Retry-After header, or the
    RetryInfo.retryDelay field Google's APIs put in the error body) over
    guessing -- free-tier per-minute quotas need an exact wait, not a
    generic backoff."""
    header_value = error.headers.get("Retry-After") if error.headers else None
    if header_value:
        try:
            return float(header_value)
        except ValueError:
            pass
    try:
        details = json.loads(body_text).get("error", {}).get("details", [])
        for detail in details:
            retry_delay = detail.get("retryDelay")
            if retry_delay:
                return float(retry_delay.rstrip("s"))
    except (json.JSONDecodeError, ValueError, AttributeError):
        pass
    return None


def _http_post_json(url, headers, body):
    """Retries transient network failures (timeout, connection reset) and
    5xx server errors (e.g. a transient "high demand" 503) with short
    backoff, and 429s by honoring the server's own stated retry delay
    (bounded by MAX_RATE_LIMIT_RETRIES, since a free-tier per-minute quota
    against 60 questions means this is the expected steady state, not an
    exceptional case). A 4xx other than 429 (e.g. a 400 schema problem) is
    never retried, since retrying it would just waste money repeating the
    same mistake -- it's a request-shape bug, not a transient condition."""
    data = json.dumps(body).encode("utf-8")
    attempt = 0
    rate_limit_attempt = 0
    while True:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body_text = error.read().decode("utf-8") if error.fp else ""
            if error.code == 429:
                rate_limit_attempt += 1
                if rate_limit_attempt > MAX_RATE_LIMIT_RETRIES:
                    raise RuntimeError(f"HTTP 429 from {url} (gave up after retries): {body_text}")
                delay = _parse_retry_delay(error, body_text)
                time.sleep(delay if delay is not None else RATE_LIMIT_FALLBACK_SECONDS)
                continue
            if error.code >= 500:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise RuntimeError(
                        f"HTTP {error.code} from {url} (gave up after retries): {body_text}"
                    )
                time.sleep(BACKOFF_BASE_SECONDS ** attempt)
                continue
            raise RuntimeError(f"HTTP {error.code} from {url}: {body_text}") from None
        except (TimeoutError, urllib.error.URLError):
            attempt += 1
            if attempt > MAX_RETRIES:
                raise
            time.sleep(BACKOFF_BASE_SECONDS ** attempt)


def _strip_schema_for_api(schema):
    """Drops keys that Gemini's/OpenAI's stricter JSON-schema dialects
    reject (title, additionalProperties), recursively. Our schemas
    (FinalAnswer, Query) are flat and single-field, so this is a light
    touch, not a general-purpose schema converter."""
    if isinstance(schema, dict):
        return {
            key: _strip_schema_for_api(value)
            for key, value in schema.items()
            if key not in ("title", "additionalProperties")
        }
    if isinstance(schema, list):
        return [_strip_schema_for_api(item) for item in schema]
    return schema


class GeminiProvider(Provider):
    """gemini-3.8-flash. The live API rejected gemini-2.5-flash on
    2026-10-18 as deprecated and pointed at this model directly. $0.75/1M
    input, $3.75/1M output -- a promotional rate through 2026-12-31, rising
    to $1.50/$7.50 on 2027-01-01 (confirmed via web search against
    third-party pricing aggregators, not Google's own ai.google.dev page
    directly; re-verify there before a large run, and again if running
    after that date)."""

    MODEL_NAME = "gemini-3.8-flash"
    PRICE_IN_PER_1K = 0.00075
    PRICE_OUT_PER_1K = 0.00375

    def _api_key(self):
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set in the environment")
        return key

    def _to_gemini_messages(self, messages):
        """Returns (system_instruction_or_None, contents_list). Gemini has
        no "system" role in `contents` (it's a separate top-level field),
        no "tool" role (a tool result becomes a user-turn functionResponse
        part), and "assistant" is called "model"."""
        system_instruction = None
        contents = []
        for message in messages:
            role = message["role"]
            if role == "system":
                system_instruction = message["content"]
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": message["content"]}]})
            elif role == "assistant":
                parts = []
                if message.get("content"):
                    parts.append({"text": message["content"]})
                for call in message.get("tool_calls") or []:
                    part = {
                        "functionCall": {
                            "name": call["function"]["name"],
                            "args": call["function"]["arguments"],
                        }
                    }
                    # Gemini 3.8's thinking variant requires its own prior
                    # thought_signature echoed back on a function call part,
                    # or it rejects the request -- round-tripped via this
                    # extra key on the tool_call dict, which agent.py never
                    # looks at (it only reads ["function"]["name"/"arguments"]).
                    if call.get("_gemini_thought_signature"):
                        part["thoughtSignature"] = call["_gemini_thought_signature"]
                    parts.append(part)
                contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": message["tool_name"],
                            "response": {"result": message["content"]},
                        }
                    }],
                })
        return system_instruction, contents

    def _to_gemini_tools(self, tools):
        declarations = []
        for tool in tools:
            function = tool["function"]
            declarations.append({
                "name": function["name"],
                "description": function["description"],
                "parameters": _strip_schema_for_api(function["parameters"]),
            })
        return [{"functionDeclarations": declarations}]

    def chat(self, messages, tools=None, response_schema=None, temperature=0):
        system_instruction, contents = self._to_gemini_messages(messages)

        generation_config = {"temperature": temperature}
        if response_schema is not None:
            generation_config["response_mime_type"] = "application/json"
            generation_config["response_schema"] = _strip_schema_for_api(
                response_schema.model_json_schema()
            )

        body = {"contents": contents, "generationConfig": generation_config}
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if tools:
            body["tools"] = self._to_gemini_tools(tools)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.MODEL_NAME}:generateContent"
        headers = {
            "x-goog-api-key": self._api_key(),
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        response_json = _http_post_json(url, headers, body)

        candidate = response_json["candidates"][0]
        parts = candidate.get("content", {}).get("parts", [])
        text_parts = [part["text"] for part in parts if "text" in part]
        function_call_parts = [part for part in parts if "functionCall" in part]

        tool_calls = None
        if function_call_parts:
            tool_calls = [
                {
                    "function": {
                        "name": part["functionCall"]["name"],
                        "arguments": part["functionCall"].get("args", {}),
                    },
                    # Carried so it can be echoed back on the next turn --
                    # see _to_gemini_messages. Not read by agent.py.
                    "_gemini_thought_signature": part.get("thoughtSignature"),
                }
                for part in function_call_parts
            ]

        usage = response_json.get("usageMetadata", {})
        tokens_in = usage.get("promptTokenCount", 0)
        tokens_out = usage.get("candidatesTokenCount", 0)

        return {
            "message": {
                "role": "assistant",
                "content": "".join(text_parts),
                "tool_calls": tool_calls,
            },
            "prompt_eval_count": tokens_in,
            "eval_count": tokens_out,
            "cost_usd": self._cost(tokens_in, tokens_out),
        }


class OpenAIProvider(Provider):
    """gpt-4o-mini. $0.15/1M input, $0.60/1M output -- confirmed via web
    search 2026-10-18 against third-party pricing aggregators (not
    OpenAI's own pricing page directly); re-verify there before a large
    run."""

    MODEL_NAME = "gpt-4o-mini"
    PRICE_IN_PER_1K = 0.00015
    PRICE_OUT_PER_1K = 0.0006

    def _api_key(self):
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set in the environment")
        return key

    def _to_openai_messages(self, messages):
        """OpenAI's roles (system/user/assistant/tool) already match ours.
        The one real gap: OpenAI requires a tool_call_id linking an
        assistant's tool_calls entry to the following tool-result message,
        which our uniform message list doesn't carry. We synthesize one
        sequential id per assistant tool call and match it to the very
        next tool-role message, since our conversation is always built
        strictly in that call-then-result order."""
        converted = []
        next_call_id = 1
        pending_call_id = None
        for message in messages:
            role = message["role"]
            if role in ("system", "user"):
                converted.append({"role": role, "content": message["content"]})
            elif role == "assistant":
                entry = {"role": "assistant", "content": message.get("content")}
                calls = message.get("tool_calls")
                if calls:
                    call_id = f"call_{next_call_id}"
                    next_call_id += 1
                    pending_call_id = call_id
                    entry["tool_calls"] = [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": calls[0]["function"]["name"],
                            "arguments": json.dumps(calls[0]["function"]["arguments"]),
                        },
                    }]
                converted.append(entry)
            elif role == "tool":
                converted.append({
                    "role": "tool",
                    "tool_call_id": pending_call_id,
                    "content": message["content"],
                })
        return converted

    def chat(self, messages, tools=None, response_schema=None, temperature=0):
        body = {
            "model": self.MODEL_NAME,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
        }
        if tools is not None:
            body["tools"] = tools  # already OpenAI-compatible, Ollama adopted this shape
        if response_schema is not None:
            schema = _strip_schema_for_api(response_schema.model_json_schema())
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.__name__,
                    "schema": schema,
                    "strict": True,
                },
            }

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        response_json = _http_post_json(url, headers, body)

        message = response_json["choices"][0]["message"]
        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = [
                {
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": json.loads(call["function"]["arguments"]),
                    }
                }
                for call in message["tool_calls"]
            ]

        usage = response_json.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        return {
            "message": {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            },
            "prompt_eval_count": tokens_in,
            "eval_count": tokens_out,
            "cost_usd": self._cost(tokens_in, tokens_out),
        }


PROVIDERS = {
    "llama3.2": OllamaProvider,
    "gemini": GeminiProvider,
    "gpt": OpenAIProvider,
}


def get_provider(name):
    if name not in PROVIDERS:
        raise ValueError(f"unknown model: {name!r} (choices: {sorted(PROVIDERS)})")
    return PROVIDERS[name]()
