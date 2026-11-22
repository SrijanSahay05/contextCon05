from fastapi.testclient import TestClient

from app.main import app


def test_healthz_reaches_postgres_and_redis() -> None:
    # the context manager runs the lifespan, which opens the engine and Redis
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
