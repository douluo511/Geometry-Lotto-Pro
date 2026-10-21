"""Recoverable research publication with a durable, first-writer intent.

The intent commits before any report or outbox side effect. A retry therefore
uses exactly the original report, including its observation time and metrics.
This does not provide external timestamp custody or formal authorization.
"""
from pathlib import Path

from ..ssq_dlt_v45 import delivery, runtime
from ..ssq_dlt_v45.store import canonical, digest, parse


def _validate_report(publication_key, report):
    if (type(report) is not dict or type(report.get('formal_A')) is not int
            or report['formal_A'] != 0 or report.get('decision') != 'NO_EDGE'
            or report.get('scope') != 'RESEARCH_UNASSIGNED'):
        raise ValueError('BLOCKED_NONRESEARCH_PUBLICATION')
    games = report.get('games')
    if (type(games) is not dict or set(games) != {'SSQ', 'DLT'}
            or any(type(data) is not dict or 'target' not in data
                   or data['target'] is not None
                   or data.get('status') not in ('BLOCKED', 'RESEARCH_UNASSIGNED')
                   for data in games.values())):
        raise ValueError('BLOCKED_UNASSIGNED_RESEARCH_GAMES_REQUIRED')
    if (type(report.get('due_slot')) is not str or not report['due_slot']
            or type(report.get('created_at')) is not str or not report['created_at']):
        raise ValueError('BLOCKED_PUBLICATION_CLOCK_REQUIRED')
    expected_key = digest(dict(due_slot=report['due_slot'], games=games))
    if type(publication_key) is not str or publication_key != expected_key:
        raise ValueError('BLOCKED_PUBLICATION_KEY_REPORT_IDENTITY_MISMATCH')


def _intent(store, publication_key, report, good, recipient):
    """Return the winning immutable intent, including after a concurrent race."""
    _validate_report(publication_key, report)
    if type(good) is not bool:
        raise ValueError('BLOCKED_PUBLICATION_READINESS_BOOLEAN_REQUIRED')
    # Detach the durable candidate from mutable objects owned by the caller.
    report = parse(canonical(report))
    candidate = dict(
        schema='GLP_WORKFLOW_PUBLISH_INTENT_1',
        publication_key=publication_key,
        due_slot=report['due_slot'],
        created_at=report['created_at'],
        research_ready=good,
        recipient=recipient,
        report_sha256=digest(report),
        report=report,
    )
    intent = store.read('workflow_publish_intent', publication_key)
    if intent is None:
        try:
            store.append('workflow_publish_intent', publication_key, candidate)
        except ValueError as exc:
            if str(exc) != 'IMMUTABLE_CONFLICT':
                raise
        intent = store.read('workflow_publish_intent', publication_key)
    if (not isinstance(intent, dict)
            or intent.get('schema') != 'GLP_WORKFLOW_PUBLISH_INTENT_1'
            or intent.get('publication_key') != publication_key
            or not isinstance(intent.get('report'), dict)
            or type(intent.get('research_ready')) is not bool
            or intent.get('report_sha256') != digest(intent['report'])
            or intent.get('created_at') != intent['report'].get('created_at')
            or intent.get('due_slot') != intent['report'].get('due_slot')
            or 'recipient' not in intent):
        raise ValueError('BLOCKED_PUBLICATION_INTENT_INTEGRITY')
    try:
        _validate_report(publication_key, intent['report'])
    except ValueError as exc:
        raise ValueError('BLOCKED_PUBLICATION_INTENT_REPORT_INTEGRITY') from exc
    return intent


def durable_publish(store, root, publication_key, report, good, recipient):
    """Commit one consistent research publication or raise a BLOCKED error.

    The first committed intent wins for this publication key. Later callers
    reuse its report, recipient and readiness even when their local clock or
    metric snapshot changed. Legacy outbox rows are never rewritten: an old
    row for the same delivery identity must bind the exact intended report.
    """
    intent = _intent(store, publication_key, report, good, recipient)
    report = intent['report']
    report_sha256 = digest(report)
    root = Path(root)
    folder = runtime.write_report(root / 'reports', report)
    outbox_id = None
    if intent['recipient']:
        outbox_id = delivery.prepare(
            store, root / 'outbox', intent['recipient'], report,
            runtime.render(report),
        )
        outbox = store.read('outbox', outbox_id)
        if (not outbox or outbox.get('report_sha256') != report_sha256
                or outbox.get('recipient') != intent['recipient']
                or outbox.get('id') != outbox_id):
            raise ValueError('BLOCKED_OUTBOX_PUBLICATION_INTENT_MISMATCH')
    result = dict(
        due_slot=intent['due_slot'],
        created_at=intent['created_at'],
        research_ready=intent['research_ready'],
        report_directory=str(folder),
        outbox_id=outbox_id,
        report=report,
    )
    try:
        store.append('workflow_publish', publication_key, result)
    except ValueError as exc:
        if str(exc) == 'IMMUTABLE_CONFLICT':
            raise ValueError('BLOCKED_WORKFLOW_PUBLICATION_INTENT_MISMATCH') from exc
        raise
    # Read back the committed value so the return value always comes from the
    # ledger, including the winner of an exact concurrent publication retry.
    return store.read('workflow_publish', publication_key)
