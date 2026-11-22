"""Restore the exact reviewed v3 package from the text-safe GitHub bundle."""
from pathlib import Path
import base64, hashlib, io, zipfile
root = Path(__file__).resolve().parent
raw = base64.b64decode((root / "quran-reels-v3.zip.b64").read_bytes())
expected = "b2587edaeb653aa8f02e0dbbccb8462692a03ea31790af9833b5cf9046b1311b"
if hashlib.sha256(raw).hexdigest() != expected:
    raise SystemExit("Bundle checksum mismatch; nothing extracted")
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    for name in z.namelist():
        dest = (root / name).resolve()
        if root not in dest.parents:
            raise SystemExit("Unsafe archive path; nothing extracted")
    z.extractall(root)
print("Verified and restored reviewed v3 package, including font and its OFL license.")
