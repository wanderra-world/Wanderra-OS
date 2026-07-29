from fastapi.testclient import TestClient

from app.api.v1.atlas import get_atlas_agent
from app.main import app


class StubAtlasAgent:
    async def chat(self, prompt: str) -> str:
        return f"Atlas received: {prompt}"


def test_atlas_chat_returns_agent_reply() -> None:
    app.dependency_overrides[get_atlas_agent] = StubAtlasAgent

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/atlas/chat", json={"message": "Hello, Atlas"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"reply": "Atlas received: Hello, Atlas"}

