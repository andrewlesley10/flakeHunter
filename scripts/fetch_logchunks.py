"""Download LogChunks (CC BY 4.0) and convert it for the evals.

    uv run python scripts/fetch_logchunks.py

LogChunks: Brandt, Panichella, Zaidman, Beller. "LogChunks: A Data Set for Build Log
Analysis", MSR 2020. https://zenodo.org/records/3632351

Raw files go to data/raw/logchunks/ and the converted items to
data/processed/logchunks.jsonl. Both are git-ignored: the data is not redistributed.
Each item holds the full log plus the hand-marked chunk explaining why the build failed.
"""

import io
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from flakehunter.parsers.junit import _reject_dtd
from flakehunter.parsers.logs import strip_ansi

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "logchunks"
OUT = ROOT / "data" / "processed" / "logchunks.jsonl"
URL = "https://zenodo.org/api/records/3632351/files/LogChunks.zip/content"


def download() -> Path:
    base = RAW / "LogChunks"
    if base.is_dir():
        return base
    RAW.mkdir(parents=True, exist_ok=True)
    print(f"downloading {URL} (24 MB)", file=sys.stderr)
    with urllib.request.urlopen(URL, timeout=300) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():  # refuse path traversal before extracting
            if member.startswith("/") or ".." in Path(member).parts:
                raise ValueError(f"unsafe path in archive: {member}")
        z.extractall(RAW)
    return base


def clean_lines(text: str) -> list[str]:
    return [strip_ansi(line).rstrip() for line in text.splitlines()]


def main() -> None:
    base = download()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with OUT.open("w", encoding="utf-8") as out:
        for label_file in sorted((base / "build-failure-reason").glob("*/*.xml")):
            _reject_dtd(label_file)  # same XXE guard as the JUnit parser
            for example in ET.parse(label_file).getroot():
                rel = example.findtext("Log") or ""
                log_path = base / "logs" / rel
                if not log_path.is_file():
                    continue
                log = clean_lines(log_path.read_text(encoding="utf-8", errors="replace"))
                chunk = clean_lines(example.findtext("Chunk") or "")
                keywords = [k.strip() for k in (example.findtext("Keywords") or "").split(",")]
                failure_id = "logchunks:" + re.sub(r"\.log$", "", rel)
                item = {
                    "failure_id": failure_id,
                    "source": "logchunks",
                    "language": rel.split("/")[0],
                    "log": log,
                    "chunk": [line for line in chunk if line.strip()],
                    "keywords": [k for k in keywords if k],
                }
                out.write(json.dumps(item) + "\n")
                count += 1
    print(f"wrote {count} items to {OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
