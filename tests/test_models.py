"""Exercise actual httpx requests and NDJSON parsing using MockTransport."""
import asyncio
import copy
import json
import unittest
from unittest.mock import patch

import httpx
from lab import models


class Chunks(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            yield part

    async def aclose(self):
        self.closed = True


class ModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests = []
        self.info = {'capabilities': ['completion', 'thinking']}
        self.parts = [b'{"message":{"thinking":"reason","content":"answer"},',
                      b'"done":false}\n\n',
                      b'{"done":true,"prompt_eval_count":71,"eval_count":9}\n']
        self.status = 200
        self.show_status = 200
        self.tags = [{'name': 'qwen3.5:4b-q8_0', 'size': 123,
                      'details': {'parameter_size': '4B', 'quantization_level': 'Q8_0'}}]
        self.streams = []

        def handle(request):
            body = json.loads(request.content) if request.content else None
            self.requests.append((request.url.path, body))
            if request.url.path == '/api/tags':
                return httpx.Response(self.status, json={'models': self.tags})
            if request.url.path == '/api/show':
                return httpx.Response(self.show_status, json=self.info)
            self.assertEqual(request.url.path, '/api/chat')
            stream = Chunks(self.parts)
            self.streams.append(stream)
            return httpx.Response(self.status, stream=stream)

        self.factory = patch.object(models, '_client', lambda: httpx.AsyncClient(
            base_url='http://test', transport=httpx.MockTransport(handle)))
        self.factory.start()
        self.addCleanup(self.factory.stop)
        # Each IsolatedAsyncioTestCase owns a distinct event loop.
        self.lock_patch = patch.object(models, '_GENERATION_LOCK', asyncio.Lock())
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)

    async def collect(self, model='qwen3.5:4b-q8_0', think=False, messages=None):
        return [event async for event in models.stream_chat(
            messages if messages is not None else [{'role': 'user', 'content': 'Hi'}],
            model, think)]

    async def test_dynamic_discovery_and_metadata(self):
        result = await models.list_models()
        self.assertEqual(result, {'models': [{
            'id': 'qwen3.5:4b-q8_0', 'name': 'qwen3.5:4b-q8_0', 'size_bytes': 123,
            'parameter_size': '4B', 'quantization': 'Q8_0', 'thinking': {'type': 'toggle'},
            'display_name': 'Qwen 3.5 · 4B · 8-bit', 'max_context_length': 32768,
            'vision': False}]})
        self.tags.append({'name': 'deepseek-r1:14b'})
        self.assertEqual(len((await models.list_models())['models']), 2)
        self.assertEqual(self.requests[1], ('/api/show', {'model': 'qwen3.5:4b-q8_0'}))

    async def test_capabilities_gate_controls(self):
        for name, info, expected in [
            ('gemma3:12b', {'capabilities': ['completion']}, {'type': 'none'}),
            ('deepseek-r1:14b', self.info, {'type': 'always'}),
            ('qwen3.5:9b-q4_K_M', self.info, {'type': 'toggle'}),
            ('gpt-oss:20b', self.info, {'type': 'levels', 'levels': ['low', 'medium', 'high']}),
            ('unknown:9b', self.info, {'type': 'always'}),
            ('qwen3:4b-thinking-2507-q4_K_M', self.info, {'type': 'always'}),
            ('qwen3.5:4b', {}, {'type': 'none'}),
        ]:
            with self.subTest(name=name):
                self.tags = [{'name': name}]
                self.info = info
                self.assertEqual((await models.list_models())['models'][0]['thinking'], expected)

    async def test_split_ndjson_thinking_content_actual_usage_and_options(self):
        events = await self.collect()
        self.assertEqual(events, [
            {'type': 'thinking', 'text': 'reason'}, {'type': 'token', 'text': 'answer'},
            {'type': 'done', 'model': 'qwen3.5:4b-q8_0', 'context': {'used': 80, 'limit': 32768, 'estimated': False,
                                         'truncated_messages': 0}}])
        payload = self.requests[-1][1]
        self.assertIs(payload['think'], False)
        self.assertEqual(payload['options'], {'num_ctx': 32768, 'num_predict': 2048})
        self.assertEqual(payload['keep_alive'], 0)
        self.assertTrue(self.streams[-1].closed)

    async def test_think_only_for_supported_values_and_models(self):
        for name, think, expected in [
            ('deepseek-r1:14b', False, None), ('unknown:latest', True, None),
            ('gpt-oss:20b', 'high', 'high'), ('qwen3.5:4b', True, True),
            ('qwen3.5:4b', None, None),
        ]:
            self.tags = [{'name': name}]
            events = await self.collect(name, think)
            self.assertEqual(events[-1]['type'], 'done')
            self.assertEqual(self.requests[-1][0], '/api/chat')
            payload = self.requests[-1][1]
            if expected is None:
                self.assertNotIn('think', payload)
            else:
                self.assertEqual(payload['think'], expected)
        for name, think in [('gpt-oss:20b', False), ('gpt-oss:20b', 'max'), ('qwen3.5:4b', 'high')]:
            self.tags = [{'name': name}]
            self.requests.clear()
            events = await self.collect(name, think)
            self.assertEqual(events[-1]['type'], 'error')
            self.assertNotIn('/api/chat', [path for path, _ in self.requests])
        self.show_status = 500
        self.tags = [{'name': 'qwen3.5:4b-q8_0'}]
        self.requests.clear()
        self.assertEqual((await self.collect())[-1]['type'], 'error')
        self.assertNotIn('/api/chat', [path for path, _ in self.requests])

    async def test_estimated_fallback_and_visible_truncation_no_history_loss(self):
        self.parts = [b'{"message":{"thinking":"abc","content":"xyz"},"done":true}\n']
        history = [{'role': 'user', 'content': 'attachment' * 9000},
                   {'role': 'user', 'content': 'Question?'}]
        original = copy.deepcopy(history)
        events = await self.collect(messages=history)
        context = events[-1]['context']
        self.assertTrue(context['estimated'])
        self.assertEqual(context['truncated_messages'], 1)
        sent = self.requests[-1][1]['messages']
        self.assertEqual(sent[-1], history[-1])
        self.assertTrue(sent[0]['content'])
        self.assertTrue(history[0]['content'].endswith(sent[0]['content']))
        self.assertEqual(history, original)
        expected = models.prepare_context(history)[1]['used'] + 6
        self.assertEqual(context['used'], expected)

    async def test_actual_zero_and_partial_counts(self):
        for counts, estimated in [
            ({'prompt_eval_count': 0, 'eval_count': 0}, False),
            ({'prompt_eval_count': 12}, True),
            ({'prompt_eval_count': -1, 'eval_count': 4}, True),
        ]:
            self.parts = [(json.dumps({'done': True, **counts}) + '\n').encode()]
            self.assertEqual((await self.collect())[-1]['context']['estimated'], estimated)

    async def test_stream_errors_and_premature_eof(self):
        for parts in [[b'{"error":"out of memory"}\n'], [b'not json\n'],
                      [b'{"message":{"content":"partial"}}\n'],
                      [b'[]\n'], [b'{"message":{"content":42}}\n']]:
            self.parts = parts
            events = await self.collect()
            self.assertEqual(events[-1]['type'], 'error')
            self.assertNotIn('done', [event['type'] for event in events])
            self.assertTrue(self.streams[-1].closed)
        self.status = 500
        self.assertEqual((await self.collect())[-1]['type'], 'error')

    async def test_discovery_errors_keep_available_models(self):
        self.show_status = 500
        result = await models.list_models()
        self.assertEqual(result['models'], [])
        self.assertIn('error', result)
        self.status = 503
        self.assertEqual((await models.list_models())['models'], [])

    async def test_connect_failure_and_invalid_context(self):
        def fail(request):
            raise httpx.ConnectError('offline', request=request)
        with patch.object(models, '_client', lambda: httpx.AsyncClient(
                base_url='http://test', transport=httpx.MockTransport(fail))):
            self.assertIn('error', await models.list_models())
            self.assertEqual((await self.collect())[-1]['type'], 'error')
        events = [e async for e in models.stream_chat([], 'x', context_limit=0)]
        self.assertEqual(events[0]['type'], 'error')
        self.assertEqual(self.requests, [])

    async def test_consumer_close_releases_http_stream(self):
        stream = models.stream_chat([{'role': 'user', 'content': 'Hi'}], 'qwen3.5:4b-q8_0')
        self.assertEqual((await anext(stream))['type'], 'thinking')
        await stream.aclose()
        self.assertTrue(self.streams[-1].closed)
        self.assertFalse(models._GENERATION_LOCK.locked())

    async def test_generation_requests_are_serialized(self):
        first = models.stream_chat([{'role': 'user', 'content': 'first'}], 'qwen3.5:4b-q8_0')
        await anext(first)
        second_started = asyncio.Event()

        async def second():
            second_started.set()
            return await self.collect()

        task = asyncio.create_task(second())
        try:
            await second_started.wait()
            self.assertEqual(sum(path == '/api/chat' for path, _ in self.requests), 1)
            await first.aclose()
            events = await asyncio.wait_for(task, timeout=2)
            self.assertEqual(events[-1]['type'], 'done')
            self.assertEqual(sum(path == '/api/chat' for path, _ in self.requests), 2)
        finally:
            await first.aclose()
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def test_unknown_model_never_reaches_chat(self):
        events = await self.collect('not-installed:latest')
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('not installed locally', events[-1]['message'])
        self.assertEqual([path for path, _ in self.requests], ['/api/tags'])

    async def test_cloud_tags_and_remote_metadata_are_rejected(self):
        for name, tag_metadata, show_metadata in [
            ('qwen3.5:397b-cloud', {}, {}),
            ('gpt-oss:cloud', {}, {}),
            ('custom:latest', {'remote_host': 'https://ollama.com'}, {}),
            ('custom:latest', {'remote_model': 'remote-id'}, {}),
            ('custom:latest', {}, {'remote_host': 'https://ollama.com'}),
            ('custom:latest', {}, {'remote_model': 'remote-id'}),
        ]:
            with self.subTest(name=name, tag=tag_metadata, show=show_metadata):
                self.tags = [{'name': name, **tag_metadata}]
                self.info = {'capabilities': ['completion'], **show_metadata}
                self.requests.clear()
                events = await self.collect(name)
                self.assertEqual(events[-1]['type'], 'error')
                self.assertIn('Remote/cloud', events[-1]['message'])
                self.assertNotIn('/api/chat', [path for path, _ in self.requests])
                self.assertEqual((await models.list_models())['models'], [])

    async def test_metadata_failure_never_reaches_chat(self):
        self.show_status = 503
        events = await self.collect()
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('metadata unavailable', events[-1]['message'])
        self.assertNotIn('/api/chat', [path for path, _ in self.requests])

    async def test_generation_budget_cutoff_is_not_reported_as_complete(self):
        self.parts = [b'{"message":{"thinking":"still reasoning"},"done":false}\n',
                      b'{"done":true,"done_reason":"length","prompt_eval_count":30,"eval_count":2048}\n']
        events = await self.collect()
        self.assertEqual(events[0]['type'], 'thinking')
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('token budget', events[-1]['message'])
        self.assertFalse(any(event['type'] == 'done' for event in events))

    async def test_switching_models_changes_inference_payload_and_reported_model(self):
        self.tags = [{'name': 'qwen3.5:4b-q8_0'}, {'name': 'qwen3.5:9b-q4_K_M'}]
        for name in ['qwen3.5:4b-q8_0', 'qwen3.5:9b-q4_K_M']:
            events = await self.collect(name)
            self.assertEqual(events[-1]['model'], name)
        payloads = [body for path, body in self.requests if path == '/api/chat']
        self.assertEqual([p['model'] for p in payloads], [t['name'] for t in self.tags])

    async def test_app_context_ceiling_ignores_model_native_context(self):
        self.info['model_info'] = {'small.context_length': 4096, 'large.context_length': 262144}
        self.assertEqual((await models.list_models())['models'][0]['max_context_length'], 32768)
        events = await self.collect()
        self.assertEqual(events[-1]['type'], 'done')
        self.assertEqual(self.requests[-1][1]['options']['num_ctx'], 32768)
