import numpy as np

from app.rag.projection import fit_pca


def test_map_has_one_point_per_chunk(client, indexed_collection):
    response = client.get(f"/collections/{indexed_collection['id']}/map")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["points"]) == indexed_collection["chunk_count"]
    assert body["dimensions"] > 2
    assert len(body["explained_variance"]) == 2 and 0 <= sum(body["explained_variance"]) <= 1.0001
    point = body["points"][0]
    assert {"chunk_id", "source_name", "location", "snippet", "x", "y"} <= point.keys()


def test_query_lands_on_the_same_map(client, indexed_collection):
    response = client.get(f"/collections/{indexed_collection['id']}/map/query", params={"q": "What does blob storage keep?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "What does blob storage keep?"
    assert isinstance(body["x"], float) and isinstance(body["y"], float)


def test_map_unknown_collection_404(client):
    assert client.get("/collections/missing-123/map").status_code == 404


def test_pca_keeps_the_widest_direction_first():
    rng = np.random.default_rng(0)
    # Spread 10x wider along dimension 0 than along the others.
    vectors = rng.normal(size=(200, 5)) * np.array([10, 1, 1, 1, 1])
    projection = fit_pca(vectors)
    assert abs(projection.components[0][0]) > 0.99
    assert projection.explained[0] > projection.explained[1] > 0
    assert np.allclose(projection.project(vectors[:1]), projection.project(vectors)[:1])


def test_pca_single_chunk_sits_at_the_centre():
    projection = fit_pca(np.ones((1, 4)))
    assert np.allclose(projection.project(np.ones(4)), [[0.0, 0.0]])
