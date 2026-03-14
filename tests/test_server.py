# tests/test_server.py
import pytest
import json
from unittest.mock import MagicMock
from ares.server.app import create_app

@pytest.fixture
def client():
    session = MagicMock()
    session.encounter_mgr.current = None
    session.encounter_mgr.completed = []
    session.encounter_mgr.progression_summary.return_value = []
    app, _ = create_app(session=session)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c

def test_health_endpoint(client):
    resp = client.get('/api/health')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert 'connected' in data

def test_session_endpoint(client):
    resp = client.get('/api/session')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert 'pulls' in data
    assert 'current' in data

def test_pulls_endpoint(client):
    resp = client.get('/api/pulls')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, list)

def test_dashboard_serves_html(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'html' in resp.data.lower()
