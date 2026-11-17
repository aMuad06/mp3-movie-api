# MP3 Movie API

This FastAPI application stores one movie collection in a SQLite database at `data/movies.db`. `POST /upload` reads a CSV with the columns `title`, `release_year`, `rating`, and `genre`, checks the columns, and replaces the stored collection through `MovieStorage` in `src/storage.py`. `GET /movies` returns stored rows with a total count, and `GET /movies/search` uses a SQL filter to return movies at or above a minimum rating. `POST /movies/process` loads the stored rows, validates and cleans them with the MP1 functions in `data_pipeline`, and saves the cleaned result back to SQLite. Responses from `GET /movies` are cached in FakeRedis by `MovieCache` in `src/cache.py`, keyed by `limit` and kept for 90 seconds, so a repeated request skips the database. After every successful upload or processing run the whole cache is cleared, which keeps later retrievals from returning outdated rows. Request logging, Pydantic models, and database setup live in `src/middleware.py`, `src/models.py`, and `src/database.py`.

## Commands

Start the API:

```
python -m uvicorn main:app --reload
```

Run the tests:

```
python -m pytest tests -v
```

## Sample Processing Request

After uploading `fixtures/sample_movies.csv`, send this body to `POST /movies/process`:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {
      "enabled": true,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

Expected result:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20,
    "rows_after": 16,
    "rows_removed": 4,
    "columns_before": 4,
    "columns_after": 4,
    "columns_removed": 0
  }
}
```

A following `GET /movies?limit=100` returns 16 rows instead of the 20 cached before processing.
