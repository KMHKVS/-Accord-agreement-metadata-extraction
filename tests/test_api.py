
from types import SimpleNamespace
from unittest.mock import MagicMock
 
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas import Agreement, FIELDS
from app.extraction import ExtractionError, extract
from app.readers import prepare_document
 
 
@pytest.fixture
def result():
    values = {key: {'value': None, 'status': 'missing', 'evidence': None, 'explanation': 'Not in document.'} for key in FIELDS}
    values['agreement_value'] = {'value': '12000', 'status': 'found', 'evidence': 'Monthly rent is 12000.', 'explanation': 'Explicit monthly rent.'}
    return Agreement(document_type='Rental agreement', summary='An agreement.', currency='INR', warnings=[], **values)
 
 
def test_preview_works_without_key(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/config').json()['configured'] is False
        response = client.post('/api/preview', files={'file': ('a.txt', b'Monthly rent is 12000.')})
        assert response.status_code == 200 and '12000' in response.json()['text']
        response = client.post('/api/extract', files={'file': ('a.txt', b'Agreement')})
        assert response.status_code == 503 and 'API key' in response.json()['detail']
 
 
def test_actual_upload_passed_to_extractor(monkeypatch, result):
    captured = {}
    def fake(doc, key, model, provider):
        captured.update(text=doc.text, key=key, model=model, provider=provider)
        return result
    monkeypatch.setattr('app.main.extract', fake)
    with TestClient(app) as client:
        response = client.post('/api/extract', files={'file': ('new.txt', b'Previously unseen document')}, data={'model': 'chosen-model'}, headers={'X-API-Key': 'test-key'})
    assert response.status_code == 200
    assert captured == {'text': 'Previously unseen document', 'key': 'test-key', 'model': 'chosen-model', 'provider': 'openai'}
    assert response.json()['result']['agreement_value']['value'] == '12000'
    assert 'test-key' not in response.text
 
 
def test_provider_request_and_date_validation(monkeypatch, result):
    result.agreement_end_date.value = '31.02.2011'
    result.agreement_end_date.status = 'found'
    client = MagicMock(); client.__enter__.return_value = client
    client.responses.parse.return_value = SimpleNamespace(output_parsed=result)
    monkeypatch.setattr('app.extraction.OpenAI', lambda **kw: client)
    output = extract(prepare_document('test.txt', b'Monthly rent is 12000.'), 'key', 'model')
    call = client.responses.parse.call_args.kwargs
    assert call['store'] is False
    assert 'Monthly rent is 12000.' in call['input'][0]['content'][0]['text']
    assert call['text_format'] is Agreement
    assert output.agreement_end_date.value == '31.02.2011'
    assert output.agreement_end_date.status == 'uncertain'
    assert any('invalid date' in message for message in output.warnings)
 
 
def test_refusal_does_not_fabricate_values(monkeypatch):
    client = MagicMock(); client.__enter__.return_value = client
    client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
    monkeypatch.setattr('app.extraction.OpenAI', lambda **kw: client)
    with pytest.raises(ExtractionError, match='complete extraction'):
        extract(prepare_document('a.txt', b'hello'), 'key', 'model')
 
 
def test_api_provider_error_is_safe(monkeypatch):
    def fail(*args):
        raise ExtractionError('The API key was rejected.', 401)
    monkeypatch.setattr('app.main.extract', fail)
    with TestClient(app) as client:
        response = client.post('/api/extract', files={'file': ('a.txt', b'hello')}, headers={'X-API-Key': 'secret'})
    assert response.status_code == 401 and 'secret' not in response.text
 
 
def test_bad_upload_is_actionable():
    with TestClient(app) as client:
        response = client.post('/api/preview', files={'file': ('a.exe', b'binary')})
    assert response.status_code == 422
 
