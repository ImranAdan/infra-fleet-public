"""Without NATS_URL the app serves as before and the pattern routes say why not."""


def test_eip_routes_answer_503_without_a_broker(client):
    response = client.get("/api/eip/status")
    assert response.status_code == 503
    assert response.get_json() == {"error": "messaging is not configured (set NATS_URL)"}
