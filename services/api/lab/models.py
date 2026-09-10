"""Async local Ollama adapter for docs/API.md; no model downloads or tools."""
import asyncio
import json
import os

import httpx

from lab.context import DEFAULT_CONTEXT_LIMIT, estimate_tokens, prepare_context

OLLAMA_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
_GENERATION_LOCK = asyncio.Lock()


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
                details = {**tag.get('details', {}), **info.get('details', {})}
                result['models'].append({
                    'id': name, 'name': tag.get('name', name),
                    'size_bytes': tag.get('size', 0),
                    'quantization': details.get('quantization_level', ''),
                    'parameter_size': details.get('parameter_size', ''),
                    'thinking': _thinking(name, info),
                })
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        result['error'] = f'Ollama unavailable: {exc}'
    return result


async def stream_chat(messages: list[dict], model: str,
                      think: bool | str | None = None,
                      context_limit: int = DEFAULT_CONTEXT_LIMIT):
    """Yield NDJSON-ready dictionaries; request-local trimming never saves history.

    Serialize generation and unload on completion to prevent this process from
    keeping multiple models resident. This intentionally trades reload latency
    for predictable memory usage. Other Ollama clients remain outside our control.
    """
    try:
        prompt, context, prediction = prepare_context(messages, context_limit)
        async with _GENERATION_LOCK:
            async with _client() as client:
                tags = await _tags(client)
                tag = next((tag for tag in tags if model == (tag.get('model') or tag.get('name'))), None)
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
                thinking = _thinking(model, info)
                payload = {'model': model, 'messages': prompt, 'stream': True,
                           'keep_alive': 0,
                           'options': {'num_ctx': context_limit, 'num_predict': prediction}}
                if thinking['type'] == 'toggle' and type(think) is bool:
                    payload['think'] = think
                elif thinking['type'] == 'levels' and think in thinking['levels']:
                    payload['think'] = think
                generated = 0
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
                            yield {'type': 'done', 'context': context}
                            return
                    yield {'type': 'error', 'message': 'Ollama stream ended before done'}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        yield {'type': 'error', 'message': f'Ollama chat failed: {exc}'}
