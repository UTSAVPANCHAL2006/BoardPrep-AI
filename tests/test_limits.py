"""Rate limits on the calls that cost money: a fake X-Forwarded-For must not get past them, and everyone together
has a ceiling. No LLM is called in these tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import limits


def makeClient() -> TestClient:
    app = FastAPI()
    app.middleware("http")(limits.limitRequests)

    @app.post("/respond")
    def respond():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    limits.recentRequests.clear()
    return TestClient(app)


def testFakeForwardedAddressesDoNotGetPastTheLimit(monkeypatch):
    monkeypatch.setitem(limits.PER_PERSON, "answer", 2)
    client = makeClient()
    codes = [client.post("/respond", headers={"X-Forwarded-For": f"10.0.0.{n}"}).status_code for n in range(3)]
    assert codes == [200, 200, 429]
    assert "try again" in client.post("/respond").json()["detail"].lower()
    assert client.get("/health").status_code == 200  # reading is never limited


def testEachRealPersonHasTheirOwnLimit(monkeypatch):
    monkeypatch.setitem(limits.PER_PERSON, "answer", 1)
    client = makeClient()
    assert client.post("/respond", headers={"CF-Connecting-IP": "203.0.113.1"}).status_code == 200
    assert client.post("/respond", headers={"CF-Connecting-IP": "203.0.113.2"}).status_code == 200
    assert client.post("/respond", headers={"CF-Connecting-IP": "203.0.113.1"}).status_code == 429


def testEveryoneTogetherHasACeiling(monkeypatch):
    monkeypatch.setitem(limits.FOR_EVERYONE, "answer", 2)
    client = makeClient()
    codes = [client.post("/respond", headers={"CF-Connecting-IP": f"203.0.113.{n}"}).status_code for n in range(3)]
    assert codes == [200, 200, 429]
