"""Multimodal and embedding coverage for lab.models using MockTransport."""
import asyncio
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


class MultimodalModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests = []
        self.info = {'capabilities': ['completion', 'thinking']}
        self.parts = [b'{"message":{"content":"ok"},"done":true,'
                      b'"prompt_eval_count":10,"eval_count":2}\n']
        self.status = 200
        self.show_status = 200
        self.tags = [{'name': 'qwen3.5:4b-q8_0', 'size': 123,
                      'details': {'parameter_size': '4B', 'quantization_level': 'Q8_0'}}]
        self.embed_response = {'model': 'nomic-embed-text', 'embeddings': [[0.1, 0.2], [0.3, 0.4]]}
        self.streams = []
        self.embed_started = asyncio.Event()
        self.embed_release = asyncio.Event()
        self.embed_release.set()

        def handle(request):
            body = json.loads(request.content) if request.content else None
            self.requests.append((request.url.path, body))
            if request.url.path == '/api/tags':
                return httpx.Response(self.status, json={'models': self.tags})
            if request.url.path == '/api/show':
                return httpx.Response(self.show_status, json=self.info)
            if request.url.path == '/api/embed':
                self.embed_started.set()
                return httpx.Response(self.status, json=self.embed_response)
            self.assertEqual(request.url.path, '/api/chat')
            stream = Chunks(self.parts)
            self.streams.append(stream)
            return httpx.Response(self.status, stream=stream)

        self.factory = patch.object(models, '_client', lambda: httpx.AsyncClient(
            base_url='http://test', transport=httpx.MockTransport(handle)))
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.lock_patch = patch.object(models, '_GENERATION_LOCK', asyncio.Lock())
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)

    async def collect(self, model='qwen3.5:4b-q8_0', messages=None):
        return [event async for event in models.stream_chat(
            messages if messages is not None else [{'role': 'user', 'content': 'Hi'}],
            model)]

    async def test_list_models_exposes_vision_capability(self):
        self.info = {'capabilities': ['completion', 'vision']}
        result = await models.list_models()
        self.assertTrue(result['models'][0]['vision'])
        self.info = {'capabilities': ['completion']}
        result = await models.list_models()
        self.assertFalse(result['models'][0]['vision'])

    async def test_list_models_hides_embedding_only_models(self):
        self.tags = [{'name': 'nomic-embed-text:latest'}]
        self.info = {'capabilities': ['embedding']}
        self.assertEqual((await models.list_models())['models'], [])

    async def test_embed_texts_batch_payload_and_validation(self):
        self.tags = [{'name': 'nomic-embed-text:latest'}]
        vectors = await models.embed_texts(['alpha', 'beta'], 'nomic-embed-text')
        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        payload = next(body for path, body in self.requests if path == '/api/embed')
        self.assertEqual(payload, {'model': 'nomic-embed-text', 'input': ['alpha', 'beta'],
                                   'truncate': False, 'keep_alive': 0})
        self.assertNotIn('/api/chat', [path for path, _ in self.requests])

    async def test_embed_texts_surfaces_context_length_errors(self):
        self.tags = [{'name': 'nomic-embed-text'}]

        def handle(request):
            body = json.loads(request.content) if request.content else None
            self.requests.append((request.url.path, body))
            if request.url.path == '/api/tags':
                return httpx.Response(self.status, json={'models': self.tags})
            if request.url.path == '/api/show':
                return httpx.Response(self.status, json=self.info)
            return httpx.Response(400, json={'error': 'the input length exceeds the context length'})

        with patch.object(models, '_client', lambda: httpx.AsyncClient(
                base_url='http://test', transport=httpx.MockTransport(handle))):
            with self.assertRaises(ValueError) as ctx:
                await models.embed_texts(['too long'], 'nomic-embed-text')
            self.assertIn('context limit', str(ctx.exception))

    async def test_embed_texts_rejects_malformed_vectors(self):
        self.tags = [{'name': 'nomic-embed-text'}]
        for response in [
            {'embeddings': [[]]},
            {'embeddings': [[0.1, 0.2], 'bad']},
            {'embeddings': [[0.1, 0.2], [0.3]]},
            {'embeddings': [[0.1, 'x']]},
            {'embeddings': []},
            [],
        ]:
            with self.subTest(response=response):
                self.requests.clear()
                self.embed_response = response
                with self.assertRaises(ValueError):
                    await models.embed_texts(['one'], 'nomic-embed-text')

    async def test_embed_requests_are_serialized(self):
        self.tags = [{'name': 'nomic-embed-text'}]
        self.embed_release.clear()
        self.embed_started.clear()

        async def slow_handle(request):
            body = json.loads(request.content) if request.content else None
            self.requests.append((request.url.path, body))
            if request.url.path == '/api/tags':
                return httpx.Response(self.status, json={'models': self.tags})
            if request.url.path == '/api/show':
                return httpx.Response(self.status, json=self.info)
            self.assertEqual(request.url.path, '/api/embed')
            self.embed_started.set()
            await self.embed_release.wait()
            count = len(body['input'])
            return httpx.Response(self.status, json={'embeddings': [[0.1, 0.2] for _ in range(count)]})

        with patch.object(models, '_client', lambda: httpx.AsyncClient(
                base_url='http://test', transport=httpx.MockTransport(slow_handle))):
            first = asyncio.create_task(models.embed_texts(['first'], 'nomic-embed-text'))
            await self.embed_started.wait()
            second_started = asyncio.Event()

            async def second():
                second_started.set()
                return await models.embed_texts(['second'], 'nomic-embed-text')

            second_task = asyncio.create_task(second())
            await second_started.wait()
            self.assertEqual(sum(path == '/api/embed' for path, _ in self.requests), 1)
            self.embed_release.set()
            first_result, second_result = await asyncio.gather(first, second_task)
            self.assertEqual(first_result, [[0.1, 0.2]])
            self.assertEqual(second_result, [[0.1, 0.2]])
            self.assertEqual(sum(path == '/api/embed' for path, _ in self.requests), 2)

    async def test_vision_model_forwards_raw_base64_images(self):
        image = 'aGVsbG8='
        self.info = {'capabilities': ['completion', 'vision']}
        events = await self.collect(messages=[{'role': 'user', 'content': 'Describe',
                                               'images': [image]}])
        self.assertEqual(events[-1]['type'], 'done')
        sent = self.requests[-1][1]['messages'][0]
        self.assertEqual(sent['images'], [image])
        self.assertEqual(sent['content'], 'Describe')

    async def test_non_vision_model_rejects_images(self):
        image = 'aGVsbG8='
        events = await self.collect(messages=[{'role': 'user', 'content': 'Describe',
                                               'images': [image]}])
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('does not support vision', events[-1]['message'])
        self.assertNotIn('/api/chat', [path for path, _ in self.requests])

    async def test_prepare_context_preserves_images_in_chat_payload(self):
        image = 'raw-base64-payload'
        self.info = {'capabilities': ['completion', 'vision']}
        history = [{'role': 'user', 'content': 'context' * 9000, 'images': [image]},
                   {'role': 'user', 'content': 'Question?', 'images': [image]}]
        events = await self.collect(messages=history)
        self.assertEqual(events[-1]['type'], 'done')
        sent = self.requests[-1][1]['messages']
        self.assertEqual(sent[-1]['images'], [image])
        self.assertTrue(any(message.get('images') == [image] for message in sent))
