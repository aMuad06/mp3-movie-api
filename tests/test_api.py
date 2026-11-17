import pandas as pd
import pytest

from src import MovieStorage
import main


def test_upload_csv(uploaded_movies):
    assert uploaded_movies == {
        "filename": "sample_movies.csv",
        "rows": 20,
        "columns": 4,
        "column_names": ["title", "release_year", "rating", "genre"],
    }


def test_get_movies_limit(client, uploaded_movies):
    response = client.get("/movies", params={"limit": 2})
    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {"id": 1, "title": "Movie A", "release_year": 2020, "rating": 8.0, "genre": "Drama"},
            {"id": 2, "title": "Movie B", "release_year": 2021, "rating": 8.5, "genre": "Comedy"},
        ],
        "total_rows": 20,
    }


def test_get_movies_empty(client):
    response = client.get("/movies")
    assert response.status_code == 200
    assert response.json() == {"data": [], "total_rows": 0}


def test_search_default_columns(client, uploaded_movies):
    response = client.get("/movies/search", params={"min_rating": 8.5, "limit": 2})
    assert response.status_code == 200
    assert response.json() == [
        {"id": 4, "title": "Movie C"},
        {"id": 2, "title": "Movie B"},
    ]


def test_search_title_and_rating(client, uploaded_movies):
    response = client.get(
        "/movies/search",
        params={"columns": ["title", "rating"], "min_rating": 8.5, "limit": 2},
    )
    assert response.status_code == 200
    assert response.json() == [
        {"id": 4, "title": "Movie C", "rating": 9.0},
        {"id": 2, "title": "Movie B", "rating": 8.5},
    ]


def test_search_bad_column(client, uploaded_movies):
    response = client.get("/movies/search", params={"columns": ["director"]})
    assert response.status_code == 400


def test_upload_replaces_collection(client, uploaded_movies, sample_csv_bytes):
    client.post(
        "/upload",
        files={"file": ("sample_movies.csv", sample_csv_bytes, "text/csv")},
    )
    response = client.get("/movies")
    assert response.json()["total_rows"] == 20


def test_bad_extension_then_health(client):
    response = client.post(
        "/upload",
        files={"file": ("movies.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "1.0.0"}


def test_process_removes_duplicates(client, uploaded_movies):
    body = {
        "validation": {
            "required_columns": ["title", "rating"],
            "numeric_columns": ["release_year", "rating"],
        },
        "processing": {
            "remove_duplicates": True,
            "missing": {"enabled": True, "axis": "rows"},
            "outliers": {"enabled": False, "columns": [], "method": "iqr", "threshold": 1.5},
        },
    }
    response = client.post("/movies/process", json=body)
    assert response.status_code == 200
    report = response.json()
    assert report["validation_rows_removed"] == 0
    assert report["cleaning_report"]["rows_before"] == 20
    assert report["cleaning_report"]["rows_after"] == 18

    assert client.get("/movies").json()["total_rows"] == 18


def test_process_empty_database(client):
    response = client.post("/movies/process", json={})
    assert response.status_code == 400


def test_upload_wrong_columns(client):
    response = client.post(
        "/upload",
        files={"file": ("movies.csv", b"name,score\nA,1\n", "text/csv")},
    )
    assert response.status_code == 400


# Part 2 required tests


def test_movies_persist(client, test_storage, uploaded_movies):
    other_storage = MovieStorage(test_storage.db_path)
    df = other_storage.get()

    assert other_storage.count_movies() == 20
    assert len(df) == 20
    assert list(df.columns) == ["title", "release_year", "rating", "genre"]

    original_titles = pd.read_csv("fixtures/sample_movies.csv")["title"].tolist()
    assert df["title"].tolist() == original_titles

    storage_rows = other_storage.select_columns(["title"], 100)
    storage_ids = [row["id"] for row in storage_rows]

    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    api_ids = [row["id"] for row in response.json()["data"]]

    assert storage_ids == list(range(1, 21))
    assert api_ids == list(range(1, 21))


def test_cache_and_processing(client, uploaded_movies, processing_body):
    response_100 = client.get("/movies", params={"limit": 100})
    response_1 = client.get("/movies", params={"limit": 1})
    assert response_100.status_code == 200
    assert response_1.status_code == 200
    assert main.cache.get(100) == response_100.json()
    assert main.cache.get(1) == response_1.json()

    repeat = client.get("/movies", params={"limit": 100})
    assert repeat.status_code == 200
    assert repeat.json() == response_100.json()

    process = client.post("/movies/process", json=processing_body)
    assert process.status_code == 200
    result = process.json()
    assert result["validation_rows_removed"] == 0
    assert result["cleaning_report"] == {
        "rows_before": 20,
        "rows_after": 16,
        "rows_removed": 4,
        "columns_before": 4,
        "columns_after": 4,
        "columns_removed": 0,
    }
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    after = client.get("/movies", params={"limit": 100})
    assert after.status_code == 200
    body = after.json()
    assert body["total_rows"] == 16

    titles = [row["title"] for row in body["data"]]
    expected_titles = ["Movie " + letter for letter in "ABCDEFGHIJKLMNOP"]
    assert titles == expected_titles

    ids = [row["id"] for row in body["data"]]
    assert ids == list(range(1, 17))

    assert main.cache.get(100) == body


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    first = client.get("/movies", params={"limit": 100})
    assert first.status_code == 200

    def fail_if_called(*args, **kwargs):
        pytest.fail("Database was called even though the response was cached")

    monkeypatch.setattr(main.storage, "select_columns", fail_if_called)
    monkeypatch.setattr(main.storage, "count_movies", fail_if_called)

    second = client.get("/movies", params={"limit": 100})
    assert second.status_code == 200
    assert second.json() == first.json()
