from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAZETTE_PDF = ROOT / "docs" / "BNS_2023_Act_45_of_2023_Gazette_English.pdf"
PAGES_DIR = ROOT / "build" / "pages"
OCR_DIR = ROOT / "ocr" / "pages"
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
DIST_DIR = ROOT / "dist"
