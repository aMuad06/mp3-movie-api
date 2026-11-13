# MP3 Movie API

FastAPI service that stores one movie collection in SQLite (`data/movies.db`). `POST /upload` replaces the collection with a CSV of `title, release_year, rating, genre`. `GET /movies` returns stored rows with a total count, `GET /movies/search` filters by minimum rating with SQL and returns selected columns, and `POST /movies/process` validates and cleans the stored data using the `data_pipeline` modules from MP1.

Run with `python -m uvicorn main:app --reload` and test with `python -m pytest tests -v`.
