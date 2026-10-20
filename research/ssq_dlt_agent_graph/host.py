"""Offline graph adapter over the existing immutable five-tool host.

Graph checkpoints are hints; only native claims, results and artifact bytes
authorize reuse. This adapter does not call private tool implementations, send
mail, discover remote sources, call a language model, or claim a whole graph
execution. Unknown native effects require reconciliation instead of retries.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from research.ssq_dlt_agent_v1.core import AgentContext, code_manifest
from research.ssq_dlt_agent_v1.policy import (
    AgentBlocked, BOUNDARY, canonical, digest, parse, validate_call, validate_config,
)
from .journal import GraphBlocked


class LegacyHost:
    """One fixed native run, using cached research histories only."""

    def __init__(self, config, run_key, *, clock=None):
        validated = validate_config(config)
        if validated['recipient'] is not None:
            raise GraphBlocked('GRAPH_RECIPIENT_MUST_BE_NONE')
        if validated['live_sources'] is not False:
            raise GraphBlocked('GRAPH_LIVE_SOURCES_NOT_ENABLED')
        self.ctx = AgentContext(validated, run_key, mode='TOOLS_SMOKE_NO_MODEL', clock=clock)

    def pin(self):
        if digest(self.ctx.config) != self.ctx.config_sha:
            raise GraphBlocked('HOST_CONFIG_CHANGED')
        if code_manifest() != self.ctx.pin:
            raise GraphBlocked('HOST_CODE_CHANGED')
        return dict(schema='GLP_GRAPH_LEGACY_HOST_1', run_id=self.ctx.run_id,
                    run_key=self.ctx.run_key, mode=self.ctx.mode,
                    config_sha256=self.ctx.config_sha, code_sha256=digest(self.ctx.pin),
                    code_manifest=deepcopy(self.ctx.pin))

    def _scope(self, name, arguments):
        scope = dict(tool=name, arguments=arguments)
        if name == 'deliver_report':
            scope['snapshot_sha256'] = digest(dict(
                snapshot=self.ctx.snapshot(), model_claims=self.ctx._rows('model_claim'),
                model_results=self.ctx._rows('model_result'),
                execution=self.ctx.ledger.read('execution_result', self.ctx.run_id)))
        return scope

    def _claims(self, run_id=None):
        run_id = self.ctx.run_id if run_id is None else run_id
        claims = [c for c in self.ctx.ledger.rows('tool_claim') if c.get('run_id') == run_id]
        for claim in claims:
            try:
                arguments = validate_call(claim['tool'], claim['arguments'])
                expected_key = digest(dict(run_id=run_id, identity=claim['identity'],
                                           attempt=claim['attempt']))
                if (arguments != claim['arguments'] or claim['claim_id'] != expected_key
                        or type(claim['attempt']) is not int or claim['attempt'] < 1
                        or type(claim['sequence']) is not int or claim['sequence'] < 1):
                    raise GraphBlocked('HOST_CLAIM_IDENTITY_MISMATCH')
                if claim['tool'] != 'deliver_report' and digest(dict(
                        tool=claim['tool'], arguments=arguments)) != claim['identity']:
                    raise GraphBlocked('HOST_CLAIM_IDENTITY_MISMATCH')
            except (KeyError, TypeError, AgentBlocked) as exc:
                raise GraphBlocked('HOST_CLAIM_IDENTITY_MISMATCH') from exc
        return claims

    def _checked_result(self, claim, row):
        try:
            if any(row.get(k) != v for k, v in claim.items()):
                raise GraphBlocked('HOST_RESULT_CLAIM_MISMATCH')
            if digest(row['evidence']) != row['evidence_sha256']:
                raise GraphBlocked('HOST_EVIDENCE_SHA_MISMATCH')
            public = row['public']
            if (type(public) is not dict or public.get('evidence_id') != claim['claim_id']
                    or any(public.get(k) != v for k, v in BOUNDARY.items())):
                raise GraphBlocked('HOST_PUBLIC_RESULT_MISMATCH')
            return deepcopy(public)
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, GraphBlocked):
                raise
            raise GraphBlocked('HOST_INVALID_RESULT') from exc

    def lookup(self, name, args):
        """Look up exactly the current native identity, including report state."""
        arguments = validate_call(name, args)
        self.pin()
        identity = digest(self._scope(name, arguments))
        matching = sorted((c for c in self._claims() if c['identity'] == identity),
                          key=lambda c: c['attempt'])
        if not matching:
            return dict(state='NOT_STARTED', result=None)
        # The native host never retries a completed identity. More than one
        # attempt is inconsistent with that contract and must not be guessed.
        if len(matching) != 1:
            raise GraphBlocked('HOST_MULTIPLE_IDENTITY_ATTEMPTS')
        claim = matching[0]
        row = self.ctx.ledger.read('tool_result', claim['claim_id'])
        if row is None:
            return dict(state='UNKNOWN', result=None)
        return dict(state='KNOWN', result=self._checked_result(claim, row))

    def pending_unknown(self):
        """List unresolved claims in this run without executing any tool."""
        self.pin()
        pending = []
        for claim in self._claims():
            row = self.ctx.ledger.read('tool_result', claim['claim_id'])
            if row is None:
                pending.append(dict(evidence_id=claim['claim_id'], tool=claim['tool'],
                                    arguments=deepcopy(claim['arguments']),
                                    sequence=claim['sequence']))
            else:
                self._checked_result(claim, row)
        return sorted(pending, key=lambda value: value['sequence'])

    def pending_unknown_in_graph_root(self):
        """A new graph thread cannot hide an unresolved native graph effect."""
        self.pin()
        pending = []
        for run in self.ctx.ledger.rows('run'):
            if not run.get('run_key', '').startswith('GRAPH:'):
                continue
            for claim in self._claims(run['run_id']):
                row = self.ctx.ledger.read('tool_result', claim['claim_id'])
                if row is None:
                    pending.append(dict(run_id=run['run_id'], evidence_id=claim['claim_id'], tool=claim['tool']))
                else:
                    self._checked_result(claim, row)
        return pending

    def call_tool(self, name, args):
        arguments = validate_call(name, args)
        known = self.lookup(name, arguments)
        if known['state'] == 'UNKNOWN' or self.pending_unknown():
            raise GraphBlocked('UNKNOWN_TOOL_OUTCOME_REQUIRES_RECONCILIATION')
        if name == 'discover_sources' and known['state'] == 'NOT_STARTED':
            # live_sources=False governs histories, but does not disable the
            # legacy discovery adapter's HTTP requests. Do not invoke it here.
            raise GraphBlocked('GRAPH_DISCOVERY_NETWORK_NOT_ENABLED')
        try:
            public = self.ctx.call_tool(name, arguments)
        except AgentBlocked as exc:
            raise GraphBlocked(str(exc)) from exc
        checked = self.lookup(name, arguments)
        if checked['state'] != 'KNOWN' or checked['result'] != public:
            raise GraphBlocked('HOST_UNBACKED_TOOL_RESULT')
        # Follow the receipt reference independently, rather than trusting a
        # returned status or even a returned reference without its native row.
        row = self.ctx.ledger.read('tool_result', public['evidence_id'])
        if row is None or row.get('run_id') != self.ctx.run_id or row.get('public') != public:
            raise GraphBlocked('HOST_UNBACKED_TOOL_RESULT')
        return deepcopy(public)

    def prepare_delivery(self):
        """Finalize immutable host metadata once, after three audited tools."""
        if self.pending_unknown():
            raise GraphBlocked('UNKNOWN_TOOL_OUTCOME_REQUIRES_RECONCILIATION')
        required = (
            ('verify_official_sources', {}, 'HISTORY_CHECKED'),
            ('run_frozen_models', {}, 'NON_FORMAL_RESEARCH_UNASSIGNED'),
            ('audit_experiment', {'action': 'inspect'}, 'AUDIT_CHECKED'),
        )
        for name, args, status in required:
            checked = self.lookup(name, args)
            if checked['state'] != 'KNOWN' or checked['result'].get('status') != status:
                raise GraphBlocked('GRAPH_DELIVERY_PREREQUISITE_NOT_MET')
        result = dict(status='GRAPH_TOOL_PIPELINE_COMPLETED', mode='TOOLS_SMOKE_NO_MODEL',
                      paid_api_calls=0, model_calls=0)
        old = self.ctx.ledger.read('execution_result', self.ctx.run_id)
        if old is not None:
            if (old.get('run_id') != self.ctx.run_id or old.get('mode') != self.ctx.mode
                    or old.get('result') != result):
                raise GraphBlocked('HOST_EXECUTION_RESULT_CONFLICT')
            return deepcopy(old)
        return deepcopy(self.ctx.finish_execution(result))

    def read_report(self):
        """Return a byte-checked report only when its native report row exists."""
        known = self.lookup('deliver_report', {})
        if known['state'] != 'KNOWN' or known['result'].get('status') != 'REPORT_SAVED':
            raise GraphBlocked('HOST_REPORT_NOT_AVAILABLE')
        result = known['result']
        record = self.ctx.ledger.read('report', result['report_id'])
        if (record is None or record.get('run_id') != self.ctx.run_id
                or record.get('report_id') != result['report_id']
                or record.get('status') != 'REPORT_SAVED'
                or record.get('delivery') != 'NOT_CONFIGURED'
                or record.get('outbox_id') is not None):
            raise GraphBlocked('HOST_REPORT_LEDGER_MISMATCH')
        directory = Path(record['report_dir']).resolve()
        root = (self.ctx.run_root / 'reports').resolve()
        if not directory.is_relative_to(root) or directory == root:
            raise GraphBlocked('HOST_REPORT_PATH_ESCAPE')
        if set(record.get('files', {})) != {'report.json', 'report.html'}:
            raise GraphBlocked('HOST_REPORT_FILES_MISMATCH')
        files = {}
        for name, expected in record['files'].items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise GraphBlocked('HOST_REPORT_PATH_ESCAPE')
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise GraphBlocked('HOST_REPORT_FILE_SHA_MISMATCH')
            files[name] = dict(path=str(path), sha256=actual)
        report = parse((directory / 'report.json').read_bytes())
        if (digest(report) != record.get('report_sha256')
                or record['report_sha256'] != record['report_id']
                or report.get('run_id') != self.ctx.run_id
                or any(report.get(k) != v for k, v in BOUNDARY.items())
                or report.get('sdk_runtime', {}).get('status') != 'GRAPH_TOOL_PIPELINE_COMPLETED'):
            raise GraphBlocked('HOST_REPORT_CONTENT_MISMATCH')
        return dict(report_id=record['report_id'], report_dir=str(directory),
                    report_sha256=record['report_sha256'], files=files,
                    report_json=files['report.json']['path'], report_html=files['report.html']['path'])
