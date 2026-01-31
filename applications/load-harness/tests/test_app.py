"""Core application tests for load-harness.

Tests for health checks, system info, and basic API functionality.
Common fixtures (client, app, client_with_auth) are provided by conftest.py.
Specialized fixtures (client_with_chaos) are defined locally.
"""

import json

import pytest
from prometheus_client import REGISTRY

from load_harness.app import create_app

def test_app_info(client):
    """Test the root endpoint returns application info."""
    response = client.get('/')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'message' in data
    assert 'timestamp' in data
    assert 'version' in data
    assert 'environment' in data
    assert data['message'] == 'Load Harness - Synthetic Workload Generator'

def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'status' in data
    assert 'timestamp' in data
    assert data['status'] == 'healthy'

def test_ready_check(client):
    """Test the readiness check endpoint."""
    response = client.get('/ready')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'status' in data
    assert 'timestamp' in data
    assert data['status'] == 'ready'

def test_version_endpoint(client):
    """Test the version endpoint returns build and deployment information."""
    response = client.get('/version')
    assert response.status_code == 200

    data = json.loads(response.data)

    # Top-level fields
    assert 'version' in data
    assert 'environment' in data
    assert 'timestamp' in data

    # Build object
    assert 'build' in data
    assert 'timestamp' in data['build']
    assert 'python_version' in data['build']
    # Verify python_version format is X.Y.Z
    assert len(data['build']['python_version'].split('.')) == 3

    # Deployment object
    assert 'deployment' in data
    assert 'pod_name' in data['deployment']
    assert 'namespace' in data['deployment']
    assert data['deployment']['namespace'] == 'applications'
    # pod_name should be the hostname (non-empty string)
    assert isinstance(data['deployment']['pod_name'], str)
    assert len(data['deployment']['pod_name']) > 0

def test_metrics_endpoint(client):
    """Test the metrics endpoint returns Prometheus format."""
    response = client.get('/metrics')
    assert response.status_code == 200

    # Prometheus metrics are in text format, not JSON
    assert response.content_type.startswith('text/plain')
    data = response.data.decode('utf-8')
    # Should contain standard Prometheus metrics
    assert 'flask_http_request_duration_seconds' in data or 'process_' in data


def test_system_info_endpoint(client):
    """Test the system info endpoint returns CPU and memory info."""
    response = client.get('/system/info')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'cpu_cores' in data
    assert 'cpu_cores_physical' in data
    assert 'memory_total_mb' in data
    assert 'memory_available_mb' in data
    assert 'timestamp' in data
    assert data['cpu_cores'] >= 1
    assert data['cpu_cores_physical'] >= 1


def test_invalid_endpoint(client):
    """Test that invalid endpoints return 404."""
    response = client.get('/nonexistent')
    assert response.status_code == 404

def test_app_creation(app):
    """Test that the app can be created successfully."""
    assert app is not None
    assert app.config['TESTING'] is True


# ---- Memory Load Tests (Non-blocking) ----

def test_memory_load_endpoint(client):
    """Test the memory load endpoint starts a background worker."""
    payload = {
        'size_mb': 10,
        'duration_seconds': 5
    }
    response = client.post('/load/memory',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'started'
    assert 'job_id' in data
    assert data['job_id'].startswith('mem_')
    assert data['size_mb'] == 10
    assert data['duration_seconds'] == 5
    assert 'timestamp' in data

    # Clean up - stop the worker
    stop_payload = {'job_id': data['job_id']}
    client.post('/load/memory/stop',
                data=json.dumps(stop_payload),
                content_type='application/json')


def test_memory_load_status_endpoint(client):
    """Test the memory load status endpoint."""
    response = client.get('/load/memory/status')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'active_jobs' in data
    assert 'total_jobs' in data
    assert 'jobs' in data
    assert 'timestamp' in data


def test_memory_load_stop_endpoint(client):
    """Test the memory load stop endpoint."""
    # First start a job
    start_payload = {'size_mb': 10, 'duration_seconds': 30}
    start_response = client.post('/load/memory',
                                 data=json.dumps(start_payload),
                                 content_type='application/json')
    job_id = json.loads(start_response.data)['job_id']

    # Stop the job
    stop_payload = {'job_id': job_id}
    response = client.post('/load/memory/stop',
                           data=json.dumps(stop_payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'stopped'
    assert job_id in data['stopped_jobs']


def test_memory_load_invalid_size(client):
    """Test memory load endpoint rejects invalid size."""
    payload = {'size_mb': 3000, 'duration_seconds': 5}  # Too large (over 2048MB limit)
    response = client.post('/load/memory',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 400

    data = json.loads(response.data)
    assert 'error' in data


def test_memory_load_invalid_duration(client):
    """Test memory load endpoint rejects invalid duration."""
    payload = {'size_mb': 10, 'duration_seconds': 400}  # Too long (over 300s limit)
    response = client.post('/load/memory',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 400

    data = json.loads(response.data)
    assert 'error' in data


def test_memory_load_invalid_duration_too_short(client):
    """Test memory load endpoint rejects too short duration."""
    payload = {'size_mb': 10, 'duration_seconds': 2}  # Too short (under 5s limit)
    response = client.post('/load/memory',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 400

    data = json.loads(response.data)
    assert 'error' in data


def test_memory_load_default_values(client):
    """Test memory load endpoint uses defaults when parameters missing."""
    payload = {}  # Empty payload
    response = client.post('/load/memory',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'started'
    assert data['size_mb'] == 50  # Default
    assert data['duration_seconds'] == 30  # Default

    # Clean up
    client.post('/load/memory/stop',
                data=json.dumps({'job_id': data['job_id']}),
                content_type='application/json')


def test_memory_load_stop_nonexistent_job(client):
    """Test stopping a non-existent memory job returns 404."""
    stop_payload = {'job_id': 'mem_nonexistent'}
    response = client.post('/load/memory/stop',
                           data=json.dumps(stop_payload),
                           content_type='application/json')
    assert response.status_code == 404

    data = json.loads(response.data)
    assert 'error' in data


# ---- Legacy Sync Memory Load Tests ----

def test_memory_load_sync_endpoint(client):
    """Test the legacy sync memory load endpoint."""
    payload = {
        'size_mb': 10,
        'duration_ms': 100
    }
    response = client.post('/load/memory/sync',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'completed'
    assert data['requested_size_mb'] == 10
    assert data['actual_bytes_allocated'] == 10 * 1024 * 1024
    assert data['requested_duration_ms'] == 100
    assert 'actual_duration_ms' in data
    assert 'allocation_time_ms' in data
    assert 'timestamp' in data


# ---- CPU Load Tests (Non-blocking) ----

def test_cpu_load_endpoint(client):
    """Test the CPU load endpoint starts workers."""
    payload = {
        'cores': 1,
        'duration_seconds': 10,
        'intensity': 3
    }
    response = client.post('/load/cpu',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'started'
    assert 'job_id' in data
    assert data['cores'] == 1
    assert data['duration_seconds'] == 10
    assert data['intensity'] == 3
    assert 'timestamp' in data

    # Clean up - stop the workers
    stop_payload = {'job_id': data['job_id']}
    client.post('/load/cpu/stop',
                data=json.dumps(stop_payload),
                content_type='application/json')


def test_cpu_load_status_endpoint(client):
    """Test the CPU load status endpoint."""
    response = client.get('/load/cpu/status')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'active_jobs' in data
    assert 'total_jobs' in data
    assert 'jobs' in data
    assert 'timestamp' in data


def test_cpu_load_stop_endpoint(client):
    """Test the CPU load stop endpoint."""
    # First start a job
    start_payload = {
        'cores': 1,
        'duration_seconds': 30,
        'intensity': 3
    }
    start_response = client.post('/load/cpu',
                                  data=json.dumps(start_payload),
                                  content_type='application/json')
    start_data = json.loads(start_response.data)
    job_id = start_data['job_id']

    # Now stop it
    stop_payload = {'job_id': job_id}
    response = client.post('/load/cpu/stop',
                           data=json.dumps(stop_payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'stopped'
    assert job_id in data['stopped_jobs']


def test_cpu_load_stop_all(client):
    """Test stopping all CPU load jobs."""
    # Start a job
    start_payload = {
        'cores': 1,
        'duration_seconds': 30,
        'intensity': 3
    }
    client.post('/load/cpu',
                data=json.dumps(start_payload),
                content_type='application/json')

    # Stop all jobs (no job_id specified)
    response = client.post('/load/cpu/stop',
                           data=json.dumps({}),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'stopped'


def test_cpu_load_invalid_cores(client):
    """Test CPU load rejects invalid core count."""
    payload = {'cores': 20, 'duration_seconds': 10}  # Too many cores
    response = client.post('/load/cpu',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 400

    data = json.loads(response.data)
    assert 'error' in data


def test_cpu_load_invalid_duration(client):
    """Test CPU load rejects invalid duration."""
    payload = {'cores': 1, 'duration_seconds': 1000}  # Too long (max 900)
    response = client.post('/load/cpu',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 400

    data = json.loads(response.data)
    assert 'error' in data


def test_cpu_load_invalid_duration_too_short(client):
    """Test CPU load rejects duration that's too short."""
    payload = {'cores': 1, 'duration_seconds': 5}  # Too short (min 10)
    response = client.post('/load/cpu',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 400

    data = json.loads(response.data)
    assert 'error' in data


def test_cpu_load_default_values(client):
    """Test CPU load uses defaults when parameters missing."""
    payload = {}  # Empty payload
    response = client.post('/load/cpu',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'started'
    assert data['cores'] == 1  # Default
    assert data['duration_seconds'] == 60  # Default
    assert data['intensity'] == 5  # Default

    # Clean up
    stop_payload = {'job_id': data['job_id']}
    client.post('/load/cpu/stop',
                data=json.dumps(stop_payload),
                content_type='application/json')


def test_cpu_load_stop_nonexistent_job(client):
    """Test stopping a non-existent job returns 404."""
    stop_payload = {'job_id': 'nonexistent_job_12345'}
    response = client.post('/load/cpu/stop',
                           data=json.dumps(stop_payload),
                           content_type='application/json')
    assert response.status_code == 404

    data = json.loads(response.data)
    assert 'error' in data


# ---- OpenAPI/Swagger Documentation Tests ----

def test_swagger_ui_endpoint(client):
    """Test that Swagger UI is accessible at /apidocs."""
    # Try without trailing slash first, then with trailing slash
    response = client.get('/apidocs')
    if response.status_code == 308:  # Redirect
        response = client.get('/apidocs/')
    assert response.status_code == 200
    assert b'swagger' in response.data.lower() or b'Swagger' in response.data


def test_openapi_spec_endpoint(client):
    """Test that OpenAPI spec is available at /apispec.json."""
    response = client.get('/apispec.json')
    assert response.status_code == 200

    data = json.loads(response.data)
    # Verify it's a valid OpenAPI spec
    assert 'info' in data
    assert data['info']['title'] == 'LoadHarness API'
    assert 'paths' in data


def test_openapi_spec_contains_all_endpoints(client):
    """Test that OpenAPI spec documents all API endpoints."""
    response = client.get('/apispec.json')
    data = json.loads(response.data)

    paths = data.get('paths', {})

    # Verify all endpoints are documented
    expected_paths = [
        '/',
        '/health',
        '/version',
        '/system/info',
        '/load/cpu',
        '/load/cpu/status',
        '/load/cpu/stop',
        '/load/cpu/work',
        '/load/memory',
    ]

    for path in expected_paths:
        assert path in paths, f"Path {path} not found in OpenAPI spec"


def test_openapi_spec_has_tags(client):
    """Test that OpenAPI spec has proper tag organization."""
    response = client.get('/apispec.json')
    data = json.loads(response.data)

    # Verify tags are present
    tags = [t['name'] for t in data.get('tags', [])]
    assert 'Health' in tags
    assert 'Load Testing' in tags
    assert 'CPU Load' in tags


# ---- Synchronous CPU Work Tests (for distributed load testing) ----

def test_cpu_work_endpoint(client):
    """Test the synchronous CPU work endpoint."""
    payload = {'iterations': 10000}
    response = client.post('/load/cpu/work',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'completed'
    assert data['iterations'] == 10000
    assert 'duration_ms' in data
    assert 'result' in data
    assert 'pod_name' in data
    assert 'timestamp' in data


def test_cpu_work_default_iterations(client):
    """Test CPU work uses default iterations when not specified."""
    payload = {}
    response = client.post('/load/cpu/work',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['iterations'] == 100000  # Default


def test_cpu_work_invalid_iterations_too_low(client):
    """Test CPU work rejects iterations below minimum."""
    payload = {'iterations': 500}  # Below 1000 minimum
    response = client.post('/load/cpu/work',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 400

    data = json.loads(response.data)
    assert 'error' in data


def test_cpu_work_invalid_iterations_too_high(client):
    """Test CPU work rejects iterations above maximum."""
    payload = {'iterations': 20000000}  # Above 10M maximum
    response = client.post('/load/cpu/work',
                           data=json.dumps(payload),
                           content_type='application/json')
    assert response.status_code == 400

    data = json.loads(response.data)
    assert 'error' in data


# ---- API Key Authentication Tests ----
# Note: client_with_auth fixture is provided by conftest.py


def test_health_no_auth_required(client_with_auth):
    """Test /health endpoint works without API key (K8s probe)."""
    response = client_with_auth.get('/health')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'healthy'


def test_ready_no_auth_required(client_with_auth):
    """Test /ready endpoint works without API key (K8s probe)."""
    response = client_with_auth.get('/ready')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'ready'


def test_protected_endpoint_requires_auth(client_with_auth):
    """Test protected endpoints return 401 without API key.

    Note: Root path '/' redirects to login (302), API endpoints return 401.
    """
    # Root path redirects to login for browser users
    response = client_with_auth.get('/')
    assert response.status_code == 302
    assert '/ui/login' in response.location

    # API endpoints return 401 JSON error
    response = client_with_auth.get('/version')
    assert response.status_code == 401

    data = json.loads(response.data)
    assert data['error'] == 'Unauthorized'
    assert 'X-API-Key' in data['message']


def test_protected_endpoint_with_valid_key(client_with_auth):
    """Test protected endpoints work with valid API key."""
    response = client_with_auth.get('/', headers={'X-API-Key': 'test-api-key-12345'})
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'message' in data


def test_protected_endpoint_with_invalid_key(client_with_auth):
    """Test protected endpoints reject invalid API key.

    Note: Root path '/' redirects to login (302), API endpoints return 401.
    """
    # Root path redirects to login even with invalid key
    response = client_with_auth.get('/', headers={'X-API-Key': 'wrong-key'})
    assert response.status_code == 302

    # API endpoints return 401 JSON error with invalid key
    response = client_with_auth.get('/version', headers={'X-API-Key': 'wrong-key'})
    assert response.status_code == 401

    data = json.loads(response.data)
    assert data['error'] == 'Unauthorized'


def test_auth_disabled_when_no_api_key(client):
    """Test all endpoints work when API_KEY not set (dev mode)."""
    # The default 'client' fixture has no API_KEY set
    response = client.get('/')
    assert response.status_code == 200

    response = client.get('/version')
    assert response.status_code == 200


def test_metrics_no_auth_required(client_with_auth):
    """Test /metrics endpoint is public (Prometheus scraping).

    Note: /metrics was made public to allow Prometheus to scrape without
    needing auth credentials. This is safe because metrics don't expose
    sensitive data and Prometheus runs inside the cluster.
    """
    response = client_with_auth.get('/metrics')
    assert response.status_code == 200


def test_apidocs_no_auth_required(client_with_auth):
    """Test /apidocs endpoint is public (browser accessible)."""
    response = client_with_auth.get('/apidocs')
    assert response.status_code == 200


def test_apispec_no_auth_required(client_with_auth):
    """Test /apispec.json endpoint is public."""
    response = client_with_auth.get('/apispec.json')
    assert response.status_code == 200


def test_ui_redirects_to_login(client_with_auth):
    """Test /ui/ redirects to login when not authenticated."""
    response = client_with_auth.get('/ui/')
    # Should redirect to login page (302) not return 401
    assert response.status_code == 302
    assert '/ui/login' in response.location


def test_login_page_accessible(client_with_auth):
    """Test /ui/login is accessible without authentication."""
    response = client_with_auth.get('/ui/login')
    assert response.status_code == 200


def test_login_with_valid_key(client_with_auth):
    """Test login with valid API key creates session."""
    response = client_with_auth.post('/ui/login', data={'api_key': 'test-api-key-12345'})
    # Should redirect to dashboard after successful login
    assert response.status_code == 302
    assert '/ui/' in response.location or response.location.endswith('/ui/')


def test_login_with_invalid_key(client_with_auth):
    """Test login with invalid API key shows error."""
    response = client_with_auth.post('/ui/login', data={'api_key': 'wrong-key'})
    assert response.status_code == 200  # Stays on login page
    assert b'Invalid API key' in response.data


# ---- Chaos Injection Tests ----

@pytest.fixture
def client_with_chaos():
    """Create a test client with 100% chaos and auth disabled."""
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass

    # Disable auth, enable chaos
    app = create_app({'API_KEY': None, 'FAIL_RATE': 1.0})
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_chaos_triggers_500(client_with_chaos):
    """Test that FAIL_RATE=1.0 causes all requests to fail."""
    response = client_with_chaos.get('/')
    assert response.status_code == 500

    data = json.loads(response.data)
    assert data['chaos'] is True
    assert 'Chaos injection triggered' in data['error']
    assert 'FAIL_RATE' in data['message']


def test_chaos_never_affects_health(client_with_chaos):
    """Test /health never fails even with FAIL_RATE=1.0."""
    response = client_with_chaos.get('/health')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'healthy'


def test_chaos_never_affects_ready(client_with_chaos):
    """Test /ready never fails even with FAIL_RATE=1.0."""
    response = client_with_chaos.get('/ready')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['status'] == 'ready'


def test_chaos_disabled_by_default(client):
    """Test no chaos when FAIL_RATE not set (default 0.0)."""
    # Make multiple requests to verify consistent behavior
    for _ in range(5):
        response = client.get('/')
        assert response.status_code == 200


# ---- Combined Auth + Chaos Tests ----

@pytest.fixture
def client_with_auth_and_chaos():
    """Create a test client with both auth and chaos enabled."""
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass

    app = create_app({
        'API_KEY': 'test-api-key-12345',
        'FAIL_RATE': 1.0
    })
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_auth_before_chaos(client_with_auth_and_chaos):
    """Test that auth is checked before chaos injection.

    Note: Root path '/' redirects to login (302), API endpoints return 401.
    """
    # Without API key, root redirects to login (auth checked before chaos)
    response = client_with_auth_and_chaos.get('/')
    assert response.status_code == 302
    assert '/ui/login' in response.location

    # API endpoints return 401 (auth checked before chaos)
    response = client_with_auth_and_chaos.get('/version')
    assert response.status_code == 401

    data = json.loads(response.data)
    assert data['error'] == 'Unauthorized'


def test_chaos_after_valid_auth(client_with_auth_and_chaos):
    """Test that chaos triggers after passing auth."""
    response = client_with_auth_and_chaos.get(
        '/',
        headers={'X-API-Key': 'test-api-key-12345'}
    )
    assert response.status_code == 500

    data = json.loads(response.data)
    assert data['chaos'] is True
