from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import PROVIDERS
from app.extraction import ExtractionError, extract
from app.main import app
from app.readers import PreparedDocument
from app.schemas import Agreement, FIELDS


def agreement_json():
    fields = {key: {'value': None, 'status': 'missing', 'evidence': None, 'explanation': 'Not present.'} for key in FIELDS}
    return Agreement(document_type='Unknown', summary='No agreement terms found.', currency=None, warnings=[], **fields).model_dump_json()


def completion(content, finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content, refusal=None))])


@pytest.fixture
def groq_client(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    factory = MagicMock(return_value=client)
    monkeypatch.setattr('app.extraction.OpenAI', factory)
    client.chat.completions.create.return_value = completion(agreement_json())
    return client, factory


def test_groq_uses_correct_endpoint_and_json_mode(groq_client):
    client, factory = groq_client
    doc = PreparedDocument('new.png', 'png', images=['data:image/jpeg;base64,TEST'])
    result = extract(doc, 'gsk_test_only', 'qwen/qwen3.8-27b', 'groq')
    assert result.party_one.value is None
    assert factory.call_args.kwargs['base_url'] == 'https://api.groq.com/openai/v1'
    client.responses.parse.assert_not_called()
    request = client.chat.completions.create.call_args.kwargs
    assert request['response_format'] == {'type': 'json_object'}
    assert request['messages'][1]['content'][-1]['image_url']['url'] == doc.images[0]
    assert 'store' not in request


def test_all_image_batches_reach_model_and_final_extraction(groq_client):
    client, _ = groq_client
    client.chat.completions.create.side_effect = [
        completion('TRANSCRIPT ONE'), completion('TRANSCRIPT TWO'), completion('TRANSCRIPT THREE'), completion(agreement_json()),
    ]
    images = [f'data:image/jpeg;base64,TEST{i}' for i in range(7)]
    result = extract(PreparedDocument('long.pdf', 'pdf', text='Original text', images=images), 'gsk_test_only', 'qwen/qwen3.8-27b', 'groq')
    requests = [call.kwargs for call in client.chat.completions.create.call_args_list]
    seen_images = []
    for request in requests[:-1]:
        batch = [part['image_url']['url'] for part in request['messages'][1]['content'] if part['type'] == 'image_url']
        assert len(batch) <= 3
        seen_images.extend(batch)
    assert seen_images == images
    final_text = requests[-1]['messages'][1]['content'][0]['text']
    for text in ['Original text', 'TRANSCRIPT ONE', 'TRANSCRIPT TWO', 'TRANSCRIPT THREE']:
        assert text in final_text
    assert any('image batches' in warning for warning in result.warnings)


def test_schema_error_retries_once(groq_client):
    client, _ = groq_client
    client.chat.completions.create.side_effect = [completion('{"wrong":true}'), completion(agreement_json())]
    extract(PreparedDocument('a.txt', 'txt', text='Agreement'), 'gsk_test_only', 'model', 'groq')
    assert client.chat.completions.create.call_count == 2


def test_repeated_schema_error_fails_without_fabrication(groq_client):
    client, _ = groq_client
    client.chat.completions.create.return_value = completion('{"wrong":true}')
    with pytest.raises(ExtractionError, match='after a retry'):
        extract(PreparedDocument('a.txt', 'txt', text='Agreement'), 'gsk_test_only', 'model', 'groq')
    assert client.chat.completions.create.call_count == 2


@pytest.mark.parametrize('content,finish,match', [('partial', 'length', 'cut off'), ('', 'stop', 'complete response'), ('no', 'content_filter', 'complete response')])
def test_incomplete_responses_fail(groq_client, content, finish, match):
    client, _ = groq_client
    client.chat.completions.create.return_value = completion(content, finish)
    with pytest.raises(ExtractionError, match=match):
        extract(PreparedDocument('a.txt', 'txt', text='Agreement'), 'gsk_test_only', 'model', 'groq')


def test_transcript_limit_does_not_silently_truncate(groq_client, monkeypatch):
    client, _ = groq_client
    monkeypatch.setattr('app.extraction.MAX_TEXT_CHARS', 10)
    client.chat.completions.create.return_value = completion('A long transcription')
    with pytest.raises(ExtractionError, match='transcript is too large'):
        extract(PreparedDocument('a.pdf', 'pdf', images=['image'] * 4), 'gsk_test_only', 'model', 'groq')


@pytest.mark.parametrize('provider,key,model', [('openai','gsk_test_only','gpt-4.1-mini'), ('groq','sk-test-only','qwen/qwen3.8-27b'), ('groq','gsk_test_only','gpt-4.1-mini')])
def test_provider_mismatches_never_send_a_request(groq_client, provider, key, model):
    _, factory = groq_client
    with pytest.raises(ExtractionError) as error:
        extract(PreparedDocument('a.txt', 'txt', text='hi'), key, model, provider)
    assert error.value.status_code == 422
    factory.assert_not_called()


def test_server_keys_are_isolated_by_provider(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'gsk_server_test_only')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk_other_provider_test_only')
    seen = []
    def fake(doc, key, model, provider):
        seen.append((key, model, provider))
        return Agreement.model_validate_json(agreement_json())
    monkeypatch.setattr('app.main.extract', fake)
    with TestClient(app) as client:
        response = client.post('/api/extract', files={'file': ('a.txt', b'Agreement')}, data={'provider': 'groq'})
        assert response.status_code == 200
        assert response.json()['provider'] == 'groq'
        assert seen == [('gsk_server_test_only', PROVIDERS['groq']['model'], 'groq')]
        data = client.get('/api/config').json()
        assert data['providers']['groq']['configured']
        assert 'gsk_server_test_only' not in str(data)


def test_groq_missing_key_does_not_fall_back_to_openai(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'sk_other_provider_test_only')
    with TestClient(app) as client:
        response = client.post('/api/extract', files={'file': ('a.txt', b'Agreement')}, data={'provider': 'groq'})
    assert response.status_code == 503 and 'Groq' in response.json()['detail']


def test_unknown_provider_rejected():
    with TestClient(app) as client:
        response = client.post('/api/extract', files={'file': ('a.txt', b'Agreement')}, data={'provider': 'unknown'}, headers={'X-API-Key': 'test'})
    assert response.status_code == 422
