"""Async local Ollama adapter for docs/API.md; no model downloads or tools."""
import asyncio
import json
import os
import re

import httpx

from lab.context import DEFAULT_CONTEXT_LIMIT, estimate_tokens, prepare_context
from lab.contracts import EmbeddingUnavailable
from lab.embedding_config import normalize_ollama_embed_error

OLLAMA_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')


def _client():
    return httpx.AsyncClient(base_url=OLLAMA_URL, trust_env=False,
                            timeout=httpx.Timeout(300, connect=5))


def _thinking(model: str, info: dict) -> dict:
    # Capabilities confirm reasoning, but do not imply that it can be disabled.
    if 'thinking' not in info.get('capabilities', []):
        return {'type': 'none'}
    name = model.rsplit('/', 1)[-1].split(':', 1)[0].lower()
    if name == 'deepseek-r1':
        return {'type': 'always'}
    if name == 'gpt-oss':
        return {'type': 'levels', 'levels': ['low', 'medium', 'high']}
    if name == 'qwen3' and 'thinking' in model.lower().split(':', 1)[-1]:
        return {'type': 'always'}
    if name in {'qwen3', 'qwen3.5', 'deepseek-v3.1'}:
        return {'type': 'toggle'}
    # Unknown reasoning models get an indicator, never invented controls.
    return {'type': 'always'}


def _is_remote(model: str, info: dict) -> bool:
    name = model.lower().rsplit('/', 1)[-1]
    return bool(info.get('remote_host') or info.get('remote_model') or
                name.endswith('-cloud') or name.endswith(':cloud'))


def _vision(info: dict) -> bool:
    return 'vision' in info.get('capabilities', [])


def _message_images(message: dict) -> list[str]:
    images = message.get('images')
    if not images:
        return []
    if not isinstance(images, list) or any(type(image) is not str or not image for image in images):
        raise ValueError('Message images must be a list of base64 strings')
    return images


def _messages_have_images(messages: list[dict]) -> bool:
    return any(_message_images(message) for message in messages)


def _validate_embeddings(texts: list[str], body) -> list[list[float]]:
    if not isinstance(body, dict):
        raise ValueError('Invalid Ollama embed response')
    embeddings = body.get('embeddings')
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise ValueError('Invalid Ollama embed response')
    validated = []
    dimension = None
    for vector in embeddings:
        if not isinstance(vector, list) or not vector:
            raise ValueError('Invalid Ollama embed vector')
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise ValueError('Invalid Ollama embed vector dimensions')
        numbers = []
        for value in vector:
            if type(value) not in (int, float):
                raise ValueError('Invalid Ollama embed vector')
            numbers.append(float(value))
        validated.append(numbers)
    return validated


async def _tags(client):
    response = await client.get('/api/tags')
    response.raise_for_status()
    tags = response.json()['models']
    if not isinstance(tags, list) or any(not isinstance(tag, dict) for tag in tags):
        raise ValueError('Invalid Ollama model list')
    return tags


async def _show(client, model):
    response = await client.post('/api/show', json={'model': model})
    response.raise_for_status()
    info = response.json()
    if not isinstance(info, dict):
        raise ValueError('Invalid Ollama model metadata')
    return info


def _find_tag(tags: list[dict], model: str):
    """Resolve Ollama's implicit `:latest` alias without changing saved settings."""
    aliases = {model}
    if ':' not in model.rsplit('/', 1)[-1]:
        aliases.add(f'{model}:latest')
    return next((tag for tag in tags
                 if (tag.get('model') or tag.get('name')) in aliases), None)


def display_name(model: str, details: dict) -> str:
    family, _, tag = model.rsplit('/', 1)[-1].partition(':')
    title = {'qwen3.5': 'Qwen 3.5', 'qwen3': 'Qwen 3', 'gemma3': 'Gemma 3',
             'deepseek-r1': 'DeepSeek R1', 'gpt-oss': 'GPT-OSS'}.get(family.lower(), family.replace('-', ' ').title())
    parameters = re.search(r'(\d+(?:\.\d+)?)b(?:-|$)', tag.lower())
    size = parameters.group(1) + 'B' if parameters else details.get('parameter_size', '')
    quant = str(details.get('quantization_level', ''))
    bits = re.match(r'Q(\d+)', quant.upper())
    precision = f'{bits.group(1)}-bit' if bits else ('16-bit' if quant.upper() in {'F16', 'BF16'} else quant)
    return ' · '.join(str(part) for part in [title, size, precision] if part)


def context_capacity(_info: dict) -> int:
    """App-wide context ceiling; independent of model-advertised native context."""
    return DEFAULT_CONTEXT_LIMIT


async def list_models() -> dict:
    result = {'models': []}
    try:
        async with _client() as client:
            tags = await _tags(client)
            for tag in tags:
                name = tag.get('model') or tag['name']
                if _is_remote(name, tag):
                    continue
                try:
                    info = await _show(client, name)
                except (httpx.HTTPError, ValueError) as exc:
                    result['error'] = f'Model metadata unavailable: {exc}'
                    continue
                if _is_remote(name, info):
                    continue
                capabilities = info.get('capabilities')
                if isinstance(capabilities, list) and capabilities and 'completion' not in capabilities:
                    continue
                details = {**tag.get('details', {}), **info.get('details', {})}
                result['models'].append({
                    'id': name, 'name': tag.get('name', name),
                    'display_name': display_name(name, details),
                    'max_context_length': context_capacity(info),
                    'size_bytes': tag.get('size', 0),
                    'quantization': details.get('quantization_level', ''),
                    'parameter_size': details.get('parameter_size', ''),
                    'thinking': _thinking(name, info),
                    'vision': _vision(info),
                })
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        result['error'] = f'Ollama unavailable: {exc}'
    return result


async def embed_texts(texts: list[str], model: str, *, generation_lock: asyncio.Lock) -> list[list[float]]:
    """Return validated embedding vectors for local models via POST /api/embed.

    Raises EmbeddingUnavailable when the model or service cannot be used, and
    ValueError when Ollama rejects the input or returns malformed vectors.
    """
    if not isinstance(texts, list) or not texts or any(type(text) is not str for text in texts):
        raise ValueError('texts must be a non-empty list of strings')
    async with generation_lock:
        try:
            async with _client() as client:
                tags = await _tags(client)
                tag = _find_tag(tags, model)
                if tag is None:
                    raise EmbeddingUnavailable(
                        f'Embedding model {model!r} is not installed locally; run `ollama pull {model}`')
                if _is_remote(model, tag):
                    raise EmbeddingUnavailable('Remote/cloud models are not supported; select a local model')
                info = await _show(client, model)
                if _is_remote(model, info):
                    raise EmbeddingUnavailable('Remote/cloud models are not supported; select a local model')
                response = await client.post('/api/embed', json={'model': model, 'input': texts,
                                                                   'truncate': False,
                                                                   'keep_alive': 0})
                if response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code >= 400:
                    try:
                        body = response.json()
                    except ValueError:
                        body = response.text
                    raise ValueError(normalize_ollama_embed_error(model, response.status_code, body))
                return _validate_embeddings(texts, response.json())
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(f'Embedding service unavailable ({type(exc).__name__}): {exc}') from exc


async def stream_chat(messages: list[dict], model: str,
                      think: bool | str | None = None,
                      context_limit: int = DEFAULT_CONTEXT_LIMIT,
                      context_metadata: dict | None = None,
                      *, generation_lock: asyncio.Lock):
    """Yield NDJSON-ready dictionaries; request-local trimming never saves history.

    Serialize generation and unload on completion to prevent this process from
    keeping multiple models resident. This intentionally trades reload latency
    for predictable memory usage. Other Ollama clients remain outside our control.
    """
    try:
        prompt, context, prediction = prepare_context(messages, context_limit)
        if context_metadata is not None:
            context = {**context, "truncated_messages": context_metadata["truncated_messages"]}
        async with generation_lock:
            async with _client() as client:
                tags = await _tags(client)
                tag = _find_tag(tags, model)
                if tag is None:
                    raise ValueError('Requested model is not installed locally')
                if _is_remote(model, tag):
                    raise ValueError('Remote/cloud models are not supported; select a local model')
                try:
                    info = await _show(client, model)
                except (httpx.HTTPError, ValueError) as exc:
                    raise ValueError('Model metadata unavailable; cannot verify local inference') from exc
                if _is_remote(model, info):
                    raise ValueError('Remote/cloud models are not supported; select a local model')
                if _messages_have_images(prompt) and not _vision(info):
                    raise ValueError('This model does not support vision; remove images or select a vision-capable model')
                thinking = _thinking(model, info)
                if thinking['type'] == 'toggle' and think is not None and type(think) is not bool:
                    raise ValueError('This model supports Thinking on/off, not low/medium/high effort levels')
                if thinking['type'] == 'levels' and think is not None and think not in thinking['levels']:
                    raise ValueError('Select a supported reasoning effort: low, medium, or high')
                payload = {'model': model, 'messages': prompt, 'stream': True,
                           'keep_alive': 0,
                           'options': {'num_ctx': context_limit, 'num_predict': prediction}}
                if thinking['type'] == 'toggle' and type(think) is bool:
                    payload['think'] = think
                elif thinking['type'] == 'levels' and think in thinking['levels']:
                    payload['think'] = think
                generated = 0
                response_model = model
                async with client.stream('POST', '/api/chat', json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if not isinstance(chunk, dict):
                            raise ValueError('Invalid Ollama stream event')
                        if chunk.get('error'):
                            yield {'type': 'error', 'message': str(chunk['error'])}
                            return
                        if isinstance(chunk.get('model'), str) and chunk['model']:
                            response_model = chunk['model']
                        message = chunk.get('message') or {}
                        if not isinstance(message, dict):
                            raise ValueError('Invalid Ollama stream message')
                        for field, kind in [('thinking', 'thinking'), ('content', 'token')]:
                            text = message.get(field, '')
                            if not isinstance(text, str):
                                raise ValueError('Invalid Ollama stream text')
                            if text:
                                generated += estimate_tokens(text)
                                yield {'type': kind, 'text': text}
                        if chunk.get('done') is True:
                            if chunk.get('done_reason') == 'length':
                                yield {'type': 'error', 'message': 'The model reached its response token budget. Partial output is saved. Try a smaller question or turn Thinking off if this model supports it.'}
                                return
                            counts = [chunk.get('prompt_eval_count'), chunk.get('eval_count')]
                            actual = all(type(n) is int and n >= 0 for n in counts)
                            context = {**context, 'used': sum(counts) if actual else context['used'] + generated,
                                       'estimated': not actual}
                            yield {'type': 'done', 'context': context, 'model': response_model}
                            return
                    yield {'type': 'error', 'message': 'Ollama stream ended before done'}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        yield {'type': 'error', 'message': f'Ollama chat failed: {exc}'}
