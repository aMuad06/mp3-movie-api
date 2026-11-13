def test_upload_csv(uploaded):
    assert uploaded == {
        "filename": "sample_movies.csv",
        "rows": 20,
        "columns": 4,
        "column_names": ["title", "release_year", "rating", "genre"],
    }


def test_get_movies_limit(client, uploaded):
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


def test_search_default_columns(client, uploaded):
    response = client.get("/movies/search", params={"min_rating": 8.5, "limit": 2})
    assert response.status_code == 200
    assert response.json() == [
        {"id": 4, "title": "Movie C"},
        {"id": 2, "title": "Movie B"},
    ]


def test_search_title_and_rating(client, uploaded):
    response = client.get(
        "/movies/search",
        params={"columns": ["title", "rating"], "min_rating": 8.5, "limit": 2},
    )
    assert response.status_code == 200
    assert response.json() == [
        {"id": 4, "title": "Movie C", "rating": 9.0},
        {"id": 2, "title": "Movie B", "rating": 8.5},
    ]


def test_search_bad_column(client, uploaded):
    response = client.get("/movies/search", params={"columns": ["director"]})
    assert response.status_code == 400


def test_upload_replaces_collection(client, uploaded, sample_csv_bytes):
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


def test_process_removes_duplicates(client, uploaded):
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
