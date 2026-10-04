from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import random
import struct
import tempfile
import time
import urllib.error
import urllib.request
import wave


PRODUCT = "AIMusicProductionSystem"
PROVIDER = "local-procedural-v1"
SAMPLE_RATE = 44100


def now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def ensure_root(root: Path) -> Path:
    root = Path(root).expanduser().resolve()
    for rel in ("projects", "evidence", "state", "backups", "quarantine"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def _project_id(prompt: str, seed: int) -> str:
    return hashlib.sha256(f"{prompt}\0{seed}".encode("utf-8")).hexdigest()[:16]


def _scale() -> list[float]:
    return [261.6256, 293.6648, 329.6276, 349.2282, 391.9954, 440.0, 493.8833, 523.2511]


def _chord_roots() -> list[float]:
    # I - V - vi - IV in C major.
    return [261.6256, 391.9954, 440.0, 349.2282]


def _synth_samples(prompt: str, seed: int, duration_seconds: float) -> list[int]:
    if not prompt.strip():
        raise ValueError("prompt must be non-empty")
    if not 2.0 <= duration_seconds <= 30.0:
        raise ValueError("duration_seconds must be between 2 and 30")

    digest = hashlib.sha256(f"{prompt}|{seed}".encode("utf-8")).digest()
    rnd = random.Random(int.from_bytes(digest[:8], "big"))
    scale = _scale()
    melody = [scale[rnd.randrange(len(scale))] for _ in range(16)]
    roots = _chord_roots()
    total = int(SAMPLE_RATE * duration_seconds)
    note_len = max(1, total // len(melody))
    chord_len = max(1, total // len(roots))
    frames: list[int] = []

    for i in range(total):
        t = i / SAMPLE_RATE
        mi = min(len(melody) - 1, i // note_len)
        ci = min(len(roots) - 1, i // chord_len)
        mt = (i % note_len) / note_len
        attack = min(1.0, mt / 0.08) if mt < 0.08 else 1.0
        release = min(1.0, (1.0 - mt) / 0.16) if mt > 0.84 else 1.0
        env = max(0.0, min(attack, release))
        root = roots[ci]
        chord = (
            math.sin(2 * math.pi * root * t)
            + 0.72 * math.sin(2 * math.pi * root * 1.25 * t)
            + 0.58 * math.sin(2 * math.pi * root * 1.5 * t)
        ) / 2.3
        lead = math.sin(2 * math.pi * melody[mi] * t) * env
        # Deterministic low-level texture; no samples or external audio assets.
        texture = math.sin(2 * math.pi * 2.0 * t + digest[8] / 255.0) * 0.03
        mixed = 0.46 * chord + 0.42 * lead + texture
        mastered = math.tanh(mixed * 1.25) * 0.76
        frames.append(max(-32767, min(32767, int(mastered * 32767))))
    return frames


def _write_wav(path: Path, samples: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        payload = bytearray()
        for sample in samples:
            payload += struct.pack("<h", sample)
        w.writeframes(payload)


def inspect_wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        frames = w.getnframes()
        raw = w.readframes(frames)
    if channels != 1 or width != 2 or rate != SAMPLE_RATE or frames <= 0:
        raise RuntimeError("unexpected WAV format")
    vals = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    peak = max(abs(v) for v in vals) / 32767.0
    rms = math.sqrt(sum(float(v) * float(v) for v in vals) / len(vals)) / 32767.0
    return {
        "channels": channels,
        "sample_width_bytes": width,
        "sample_rate": rate,
        "frame_count": frames,
        "duration_seconds": frames / rate,
        "peak": peak,
        "rms": rms,
    }


def create_project(root: Path, prompt: str, seed: int = 42, duration_seconds: float = 8.0) -> dict:
    root = ensure_root(root)
    pid = _project_id(prompt, seed)
    project_dir = root / "projects" / pid
    project_dir.mkdir(parents=True, exist_ok=True)
    wav_path = project_dir / "master.wav"
    samples = _synth_samples(prompt, seed, duration_seconds)
    _write_wav(wav_path, samples)
    metrics = inspect_wav(wav_path)
    wav_hash = sha256_file(wav_path)

    project = {
        "schema": "ai-music-project-v1",
        "project_id": pid,
        "prompt": prompt,
        "seed": seed,
        "provider": PROVIDER,
        "provider_kind": "LOCAL_PROCEDURAL_NOT_EXTERNAL_AI_MODEL",
        "created_at": now_iso(),
        "pipeline": [
            "idea",
            "structure",
            "chords",
            "melody",
            "arrangement",
            "mix",
            "master",
            "review",
            "export",
            "evidence_replay",
        ],
        "implemented_boundaries": {
            "lyrics": "NOT IMPLEMENTED",
            "human_or_ai_vocal": "NOT VERIFIED",
            "external_ai_model": "NOT VERIFIED",
            "external_model_license": "NOT APPLICABLE TO LOCAL PROCEDURAL AUDIO; EXTERNAL MODEL PATH NOT VERIFIED",
        },
        "audio": {
            "path": "master.wav",
            "sha256": wav_hash,
            **metrics,
        },
        "asset_provenance": {
            "external_audio_samples": [],
            "external_model_assets": [],
            "license_status": "OWNED_GENERATED_AUDIO_NO_EXTERNAL_ASSETS",
        },
    }
    write_json(project_dir / "project.json", project)
    receipt = {
        "schema": "ai-music-generation-evidence-v1",
        "status": "PASS",
        "project_id": pid,
        "provider": PROVIDER,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "seed": seed,
        "wav_sha256": wav_hash,
        "project_sha256": sha256_file(project_dir / "project.json"),
        "generated_at": now_iso(),
        "boundary": "Real audio was generated locally; this is not evidence of an external AI music-model/provider chain.",
    }
    write_json(root / "evidence" / f"generation_{pid}.json", receipt)
    return {"status": "PASS", "project": project, "evidence": receipt, "project_dir": str(project_dir)}


def repair(root: Path) -> dict:
    root = ensure_root(root)
    invalid: list[dict] = []
    checked = 0
    for p in sorted((root / "projects").glob("*/project.json")):
        checked += 1
        obj = read_json(p)
        if not isinstance(obj, dict):
            invalid.append({"project": str(p.parent.name), "reason": "project_json_invalid"})
            continue
        audio = obj.get("audio") or {}
        wav = p.parent / str(audio.get("path") or "master.wav")
        expected = str(audio.get("sha256") or "")
        if not wav.is_file():
            invalid.append({"project": p.parent.name, "reason": "wav_missing"})
        elif expected and sha256_file(wav) != expected:
            invalid.append({"project": p.parent.name, "reason": "wav_hash_mismatch"})
    result = {
        "schema": "ai-music-repair-v1",
        "status": "PASS" if not invalid else "WARN",
        "checked_projects": checked,
        "invalid": invalid,
        "user_projects_deleted": False,
        "repair_policy": "fail/report; never delete user audio automatically",
        "generated_at": now_iso(),
    }
    write_json(root / "state" / "repair_status.json", result)
    return result


def advanced_analysis(root: Path) -> dict:
    root = ensure_root(root)
    projects = []
    for p in sorted((root / "projects").glob("*/project.json")):
        obj = read_json(p)
        if isinstance(obj, dict):
            projects.append(obj)
    durations = [float((x.get("audio") or {}).get("duration_seconds") or 0) for x in projects]
    result = {
        "schema": "ai-music-advanced-analysis-v1",
        "status": "PASS",
        "project_count": len(projects),
        "total_audio_seconds": round(sum(durations), 6),
        "providers": sorted({str(x.get("provider")) for x in projects if x.get("provider")}),
        "provenance_complete_for_local_audio": all(
            bool((x.get("audio") or {}).get("sha256")) and
            (x.get("asset_provenance") or {}).get("external_audio_samples") == []
            for x in projects
        ),
        "business_gaps": [
            "external AI music-model/provider lineage NOT VERIFIED",
            "external model/license terms NOT VERIFIED",
            "lyrics pipeline NOT IMPLEMENTED",
            "AI/human vocal pipeline NOT VERIFIED",
            "real production updater Release N->N+1 BLOCKED until independent repository exists",
        ],
        "generated_at": now_iso(),
    }
    write_json(root / "state" / "advanced_analysis.json", result)
    return result


def update_status(root: Path) -> dict:
    root = ensure_root(root)
    result = {
        "schema": "ai-music-update-status-v1",
        "status": "BLOCKED",
        "reason": "independent production repository/release manifest/trusted signing key not configured",
        "positive_production_update": "BLOCKED",
        "user_projects_modified": False,
        "generated_at": now_iso(),
    }
    write_json(root / "state" / "update_status.json", result)
    return result


def network_probe(url: str, report_path: Path | None = None) -> dict:
    if not url.lower().startswith("https://"):
        raise ValueError("HTTPS required")
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "AI-Music-Production-System/reauthored-candidate",
                    "Accept": "application/vnd.github+json, application/json;q=0.9, */*;q=0.1",
                },
            )
            started = time.monotonic()
            with urllib.request.urlopen(req, timeout=15) as response:
                data = response.read(1024 * 1024)
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("content-type") or "")
            if not 200 <= status < 300:
                raise RuntimeError(f"HTTP {status}")
            report = {
                "schema": "ai-music-real-network-v1",
                "status": "PASS",
                "url": url,
                "http_status": status,
                "bytes": len(data),
                "content_type": content_type,
                "payload_sha256": hashlib.sha256(data).hexdigest(),
                "attempt": attempt,
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "scope": "authoritative GitHub project-control/source-reference connectivity; not external AI generation-provider acceptance",
                "generated_at": now_iso(),
            }
            if report_path:
                write_json(report_path, report)
            return report
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(0.8 * attempt)
    report = {
        "schema": "ai-music-real-network-v1",
        "status": "FAIL",
        "url": url,
        "error": f"{type(last).__name__}: {last}",
        "generated_at": now_iso(),
    }
    if report_path:
        write_json(report_path, report)
    return report


def self_test(source_sha: str, executable: Path | None, nonce: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="ai_music_selftest_") as td:
        result1 = create_project(Path(td) / "a", "strict acceptance test", 12345, 3.0)
        result2 = create_project(Path(td) / "b", "strict acceptance test", 12345, 3.0)
        p1 = Path(result1["project_dir"]) / "master.wav"
        p2 = Path(result2["project_dir"]) / "master.wav"
        if sha256_file(p1) != sha256_file(p2):
            raise RuntimeError("deterministic audio hash mismatch")
        metrics = inspect_wav(p1)
        if metrics["rms"] <= 0.01 or metrics["peak"] <= 0.05:
            raise RuntimeError("generated audio is effectively silent")
    exe_hash = sha256_file(executable) if executable and executable.is_file() else "SOURCE_MODE"
    return {
        "schema": "ai-music-exact-self-test-v1",
        "status": "PASS",
        "product": PRODUCT,
        "source_sha": source_sha,
        "exe_sha256": exe_hash,
        "nonce": nonce,
        "deterministic_audio": "PASS",
        "real_audio_output": "PASS",
        "provider": PROVIDER,
        "external_ai_provider": "NOT VERIFIED",
        "generated_at": now_iso(),
    }
