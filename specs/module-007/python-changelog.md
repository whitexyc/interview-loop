# Module-007 Python Changelog

## Added

- `ai_service/requirements.txt` — Added `PyMuPDF==1.24.1` for PDF text extraction
- `ai_service/main.py` — Added `POST /ai/rag/documents/upload` endpoint
  - Accepts PDF file via `multipart/form-data` (UploadFile)
  - Validates file type and non-empty content
  - Uses PyMuPDF (fitz) to extract text content per page with page markers
  - Extracts page count from PDF metadata
  - Falls back to filename (without extension) for title when not provided
  - Falls back to `pdf_upload:{filename}` for source when not provided
  - Calls existing `rag_engine.add_document()` for vectorization and storage
  - Returns `page_count` alongside standard `add_document` result
