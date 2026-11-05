"""Replay trusted original model bytes, never executable ledger/workspace data.

Registry entries are reviewed repository code, not self-authenticating ledger
assertions. This is model reproducibility only, never official/TSA provenance.
"""
from __future__ import annotations

import hashlib
import sys
import threading
import types
from pathlib import Path

from . import core


SOURCES = {
    'f780a577d514eb36b4f3bcc4ecdecc92993ffb5fc96d03210cdf61078ff52941': 'core_lf.source',
    'c9aea92c45609247cf9c6177edf927e43a26b8a3628b6e83efc8c80c95cb9282': 'core_crlf.source',
}
OBSERVED_SOURCE = '138d32349248c9c0ef0e86dd0c9e2ba9ec504a6194d058f68db47f4e001f19db'
SCORECARDS = {
    'f780a577d514eb36b4f3bcc4ecdecc92993ffb5fc96d03210cdf61078ff52941':
        ('scorecard_lf.source', '88f9be76a328783c21e368d1edaeca446c69298edfdaafca9ecbbe94d5f46afa'),
    'c9aea92c45609247cf9c6177edf927e43a26b8a3628b6e83efc8c80c95cb9282':
        ('scorecard_crlf.source', '97092796cd9f679ae3a0070b6e2da575cffbd5bfdf34f1c5c6fac3f7a66c07e0'),
}
_LOCK = threading.RLock()
_CACHE = {}
_SCORECARD_CACHE = {}


def _artifact(name, expected):
    path = Path(__file__).parent / 'model_versions' / name
    if path.is_symlink() or path.parent.is_symlink():
        raise core.GateError('REPLAY_SOURCE_ARTIFACT_LINK_FORBIDDEN')
    try:
        with path.open('rb') as stream:
            raw = stream.read(128_001)
    except OSError as exc:
        raise core.GateError('REPLAY_SOURCE_ARTIFACT_MISSING') from exc
    if len(raw) > 128_000 or hashlib.sha256(raw).hexdigest() != expected:
        raise core.GateError('REPLAY_SOURCE_ARTIFACT_HASH_MISMATCH')
    return path, raw


def resolve_core(source_sha256):
    """Only fixed package artifacts or the exact currently installed core."""
    from .statistics import FAIR_D2
    if FAIR_D2 != {g: r['d2'] for g, r in core.RULES.items()}:
        raise core.GateError('REPLAY_STATISTICAL_BASELINE_MISMATCH')
    if (not isinstance(source_sha256, str) or len(source_sha256) != 64
            or any(c not in '0123456789abcdef' for c in source_sha256)):
        raise core.GateError('REPLAY_SOURCE_NOT_REGISTERED')
    name = SOURCES.get(source_sha256)
    if name is None:
        current = hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest()
        if source_sha256 != current:
            raise core.GateError('REPLAY_SOURCE_NOT_REGISTERED')
        return core
    # Recheck both files even on cached reads: deletion or later modification
    # cannot be hidden by sys.modules or a previously successful replay.
    path, raw = _artifact(name, source_sha256)
    observed_path, observed_raw = _artifact('observed_snapshot.source', OBSERVED_SOURCE)
    with _LOCK:
        if source_sha256 in _CACHE:
            return _CACHE[source_sha256]
        package_name = __package__ + '._frozen_' + source_sha256
        package = types.ModuleType(package_name)
        package.__path__ = []  # no filesystem import search for other code
        sys.modules[package_name] = package
        model = types.ModuleType(package_name + '.core')
        model.__file__, model.__package__ = str(path), package_name
        observed = types.ModuleType(package_name + '.observed_snapshot')
        observed.__file__, observed.__package__ = str(observed_path), package_name
        sys.modules[model.__name__] = model
        sys.modules[observed.__name__] = observed
        try:
            # Only the exact hash-verified, reviewed repository bytes execute.
            # Never import a .pyc or code supplied by a DB or caller path.
            exec(compile(raw, str(path), 'exec'), model.__dict__)
            model.GateError = core.GateError
            exec(compile(observed_raw, str(observed_path), 'exec'), observed.__dict__)
            if (model.model_source_sha256() != source_sha256
                    or model.MODELS != core.MODELS or model.RULES != core.RULES
                    or model.NULL_SEED != core.NULL_SEED):
                raise core.GateError('REPLAY_REGISTERED_CONTRACT_MISMATCH')
        except BaseException:
            for key in (observed.__name__, model.__name__, package_name):
                sys.modules.pop(key, None)
            raise
        _CACHE[source_sha256] = model
        return model


def manifest_core(manifest):
    models = manifest.get('models')
    if (not isinstance(models, dict) or set(models) != set(core.MODELS)
            or any(not isinstance(p, dict) for p in models.values())):
        raise core.GateError('REPLAY_INCOMPLETE_MODEL_IDENTITIES')
    sources = {p.get('model_source_sha256') for p in models.values()}
    if len(sources) != 1:
        raise core.GateError('REPLAY_MIXED_MODEL_SOURCES')
    return resolve_core(sources.pop())


def load_snapshot(conn, run_id, lottery):
    manifest = core.validate_run_manifest_record(conn, run_id)
    if manifest is None:
        raise core.GateError('V47_MANIFEST_REQUIRED')
    return manifest_core(manifest).load_registered_snapshot(conn, run_id, lottery)


def resolve_scorecard(conn, run_id):
    """Use the original report builder so prior receipt bytes stay reproducible.

    Registered original LF and CRLF installations have corresponding scorer
    artifacts. Mixed/unknown historic report identities are not silently mapped.
    The current convergence facade retains independent full-card validation.
    """
    manifest = core.validate_run_manifest_record(conn, run_id)
    if manifest is None:
        raise core.GateError('V47_MANIFEST_REQUIRED')
    model = manifest_core(manifest)
    source = model.model_source_sha256()
    artifact = SCORECARDS.get(source)
    if artifact is None:
        return None
    path, raw = _artifact(*artifact)
    with _LOCK:
        if source in _SCORECARD_CACHE:
            return _SCORECARD_CACHE[source]
        from . import convergence
        package_name = model.__package__
        sys.modules[package_name + '.convergence'] = convergence
        # The old report imports only FAIR_D2. Bind it to the original core's
        # lottery rules rather than silently importing today's statistics.
        statistics = types.ModuleType(package_name + '.statistics')
        statistics.FAIR_D2 = {g: r['d2'] for g, r in model.RULES.items()}
        sys.modules[statistics.__name__] = statistics
        module = types.ModuleType(package_name + '.prospective_scorecard')
        module.__file__, module.__package__ = str(path), package_name
        exec(compile(raw, str(path), 'exec'), module.__dict__)
        _SCORECARD_CACHE[source] = module
        return module


def validate_prediction(prediction, snapshot):
    model = resolve_core(prediction.get('model_source_sha256'))
    model.validate_forecast(prediction, snapshot)
    if prediction != model.forecast(snapshot, prediction['model']):
        raise core.GateError('FROZEN_FULL_CARD_REPLAY_MISMATCH')
    return True


def score_prediction(prediction, result):
    return resolve_core(prediction.get('model_source_sha256')).score(prediction, result)
