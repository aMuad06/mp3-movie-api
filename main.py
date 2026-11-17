import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import (
    HealthResponse,
    ProcessConfig,
    log_requests,
    setup_logging,
    MovieCache,
    MovieStorage,
    MovieUploadInfo,
    MovieDataResponse,
    MovieProcessingReport,
)
from src.storage import MOVIE_COLUMNS

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Data Processing API", version="1.0.0")
app.middleware("http")(log_requests)

storage = MovieStorage()
cache = MovieCache()


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return HealthResponse(status="ok", version=app.version)


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Read a CSV upload and replace the stored movie collection."""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix != ".csv":
        logger.warning(f"Unsupported file format: {suffix or '(none)'}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{suffix or 'none'}'. Please upload a .csv file.",
        )

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except pd.errors.EmptyDataError:
        logger.warning(f"Empty CSV upload: {filename}")
        raise HTTPException(status_code=400, detail="The uploaded CSV file is empty.")
    except pd.errors.ParserError as e:
        logger.warning(f"Could not parse CSV {filename}: {e}")
        raise HTTPException(status_code=400, detail="The uploaded file could not be parsed as CSV.")
    except UnicodeDecodeError:
        logger.warning(f"Could not decode CSV: {filename}")
        raise HTTPException(status_code=400, detail="The uploaded file is not valid UTF-8 text.")

    if sorted(df.columns) != sorted(MOVIE_COLUMNS):
        logger.warning(f"Wrong columns in {filename}: {list(df.columns)}")
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have exactly these columns: {MOVIE_COLUMNS}",
        )
    if df.empty:
        logger.warning(f"No data rows in {filename}")
        raise HTTPException(status_code=400, detail="The uploaded CSV has no data rows.")

    df = df[MOVIE_COLUMNS]
    storage.save(df)
    cache.invalidate()
    logger.info(f"Uploaded movies: filename={filename}, rows={len(df)}")

    return {
        "filename": filename,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
    }


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return up to limit stored movies and the total count."""
    cached = cache.get(limit)
    if cached is not None:
        logger.info(f"Returned cached movies: limit={limit}")
        return cached

    data = storage.select_columns(MOVIE_COLUMNS, limit)
    total_rows = storage.count_movies()
    response = {"data": data, "total_rows": total_rows}

    cache.set(limit, response)
    logger.info(f"Retrieved movies: returned_rows={len(data)}")
    return response


@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Return id plus selected columns for movies at or above min_rating."""
    try:
        results = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    logger.info(
        f"Queried movies: columns={columns}, min_rating={min_rating}, "
        f"returned_rows={len(results)}"
    )
    return results


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and clean the stored movies using MP1 functions."""
    df = storage.get()
    if df.empty:
        logger.warning("Process called with no stored movies")
        raise HTTPException(status_code=400, detail="No movies stored. Upload a CSV first.")

    config_dict = config.model_dump()
    required_columns = config_dict["validation"]["required_columns"]
    numeric_columns = config_dict["validation"]["numeric_columns"]

    for col in numeric_columns:
        if col not in df.columns:
            logger.warning(f"Numeric column not found: {col}")
            raise HTTPException(status_code=400, detail=f"Numeric column not found: {col}")

    try:
        validated = validate_dataframe(df, required_columns, numeric_columns)
        validation_removed = len(df) - len(validated)
        logger.info(f"Validated movies: rows_removed={validation_removed}")

        before = validated.copy()
        processed = process_data(validated, config_dict)
    except ValueError as error:
        logger.warning(f"Processing failed: {error}")
        raise HTTPException(status_code=400, detail=str(error))

    report = create_cleaning_report(before, processed)
    storage.save(processed)
    cache.invalidate()
    logger.info(
        f"Processed movies: validation_removed={validation_removed}, "
        f"rows_before={report['rows_before']}, rows_after={report['rows_after']}"
    )

    return {
        "validation_rows_removed": validation_removed,
        "cleaning_report": report,
    }
