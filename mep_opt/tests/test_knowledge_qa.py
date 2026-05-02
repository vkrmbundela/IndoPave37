import json

from fastapi.testclient import TestClient

from mep_opt.web.knowledge_qa import ChunkFilters, IrcKnowledgeService
from mep_opt.web import main as web_main


def _write_chunks(tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = knowledge_dir / "chunks.jsonl"

    rows = [
        {
            "chunk_id": "p010_c001",
            "page_start": 10,
            "page_end": 10,
            "heading": "Design Principles",
            "text": "Fatigue performance equation: Nf = A*(1/eps_t)^3.89 for bituminous layer.",
        },
        {
            "chunk_id": "p020_c001",
            "page_start": 20,
            "page_end": 20,
            "heading": "Traffic",
            "text": "Traffic growth rate and cumulative msa computation procedure.",
        },
        {
            "chunk_id": "p030_c001",
            "page_start": 30,
            "page_end": 30,
            "heading": "Pavement Composition",
            "text": "Granular base and sub-base thickness recommendations.",
        },
    ]

    with chunks_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")

    return knowledge_dir


def _build_api_client(tmp_path, monkeypatch):
    knowledge_dir = _write_chunks(tmp_path)
    service = IrcKnowledgeService(knowledge_dir=knowledge_dir)
    monkeypatch.setattr(web_main, "knowledge_service", service)
    return TestClient(web_main.app)


def _build_missing_corpus_client(tmp_path, monkeypatch):
    # Intentionally point to a directory with no chunks.jsonl to assert 404 behavior.
    missing_knowledge_dir = tmp_path / "missing_knowledge"
    service = IrcKnowledgeService(knowledge_dir=missing_knowledge_dir)
    monkeypatch.setattr(web_main, "knowledge_service", service)
    return TestClient(web_main.app)


def test_search_prefers_fatigue_equation_chunk(tmp_path):
    knowledge_dir = _write_chunks(tmp_path)
    service = IrcKnowledgeService(knowledge_dir=knowledge_dir)

    payload = service.search(query="fatigue equation Nf eps_t", top_k=2)
    assert payload["returned_chunks"] >= 1
    assert payload["results"][0]["chunk_id"] == "p010_c001"
    assert payload["results"][0]["has_equation"] is True


def test_search_respects_metadata_filters(tmp_path):
    knowledge_dir = _write_chunks(tmp_path)
    service = IrcKnowledgeService(knowledge_dir=knowledge_dir)

    filters = ChunkFilters(page_min=18, page_max=25, has_equation=False)
    payload = service.search(query="traffic growth rate", top_k=3, filters=filters)

    assert payload["candidate_chunks"] == 1
    assert payload["returned_chunks"] == 1
    assert payload["results"][0]["chunk_id"] == "p020_c001"


def test_ask_returns_answer_and_citations(tmp_path):
    knowledge_dir = _write_chunks(tmp_path)
    service = IrcKnowledgeService(knowledge_dir=knowledge_dir)

    payload = service.ask(query="What is the fatigue equation for bituminous layer?", top_k=2)
    assert payload["retrieved_chunks"] >= 1
    assert payload["answer"]
    assert len(payload["citations"]) >= 1
    assert payload["citations"][0]["chunk_id"] == "p010_c001"


def test_search_endpoint_returns_hits_and_hides_full_text(tmp_path, monkeypatch):
    client = _build_api_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/knowledge/search",
        json={"query": "fatigue equation eps_t", "top_k": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["returned_chunks"] >= 1
    assert payload["results"][0]["chunk_id"] == "p010_c001"
    assert "text" not in payload["results"][0]


def test_ask_endpoint_returns_answer_and_citations(tmp_path, monkeypatch):
    client = _build_api_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/knowledge/ask",
        json={"query": "Explain fatigue equation for bituminous layer", "top_k": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"]
    assert payload["retrieved_chunks"] >= 1
    assert len(payload["citations"]) >= 1
    assert payload["citations"][0]["chunk_id"] == "p010_c001"


def test_search_endpoint_rejects_invalid_page_filter_range(tmp_path, monkeypatch):
    client = _build_api_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/knowledge/search",
        json={
            "query": "traffic",
            "filters": {"page_min": 30, "page_max": 20},
        },
    )

    assert response.status_code == 400
    assert "page_min" in response.json()["detail"]


def test_search_endpoint_returns_404_when_corpus_file_missing(tmp_path, monkeypatch):
    client = _build_missing_corpus_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/knowledge/search",
        json={"query": "fatigue equation"},
    )

    assert response.status_code == 404
    assert "Knowledge chunks file not found" in response.json()["detail"]
