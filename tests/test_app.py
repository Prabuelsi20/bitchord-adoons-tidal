from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_reports_provider_and_no_fake_playback():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['provider'] == 'TIDAL'
    assert r.json()['playback_ready'] is False

def test_manifest_shape():
    r = client.get('/manifest.json')
    assert r.status_code == 200
    body = r.json()
    assert body['id'] and 'search' in body['resources'] and 'stream' in body['resources']

def test_stream_not_faked():
    r = client.get('/stream/td:123')
    assert r.status_code == 501
