#!/usr/bin/env python3
"""Fetch the upstream JSONNET templates used by the application.

The project deliberately uses the upstream implementations rather than
reimplementing their taxonomies or filing protocol.  This script only
bootstraps the JSONNET template repository, which is not a Python package.
"""
from __future__ import annotations
import io
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "sample_data" / "ixbrl-reporter-jsonnet"
URL = os.getenv(
    "IXBRL_REPORTER_JSONNET_ARCHIVE_URL",
    "https://github.com/cybermaggedon/ixbrl-reporter-jsonnet/archive/refs/heads/master.zip",
)

def main() -> None:
    print(f"Downloading {URL}")
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root_names = [n.split("/", 1)[0] for n in archive.namelist() if "/" in n]
        if not root_names:
            raise RuntimeError("Unexpected upstream archive layout")
        source_root = root_names[0]
        tmp = ROOT / ".upstream-jsonnet.tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir()
        archive.extractall(tmp)
        extracted = tmp / source_root
        if not (extracted / "lib" / "frs102.libsonnet").exists():
            raise RuntimeError("Downloaded archive does not contain lib/frs102.libsonnet")
        if TARGET.exists():
            shutil.rmtree(TARGET)
        shutil.copytree(extracted, TARGET)
        shutil.rmtree(tmp)
    print(f"Installed ixbrl-reporter-jsonnet into {TARGET}")

if __name__ == "__main__":
    main()
