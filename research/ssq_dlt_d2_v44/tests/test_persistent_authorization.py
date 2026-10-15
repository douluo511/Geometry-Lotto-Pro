"""Synthetic real signatures and persistent atomic replay rejection; no A trust."""
import base64
import importlib.util
import tempfile
import unittest
from pathlib import Path

from research.ssq_dlt_d2_v44.ledger import Ledger, canonical, digest
from research.ssq_dlt_d2_v44.scoring import AdmissionBlocked
from research.ssq_dlt_d2_v44.tests import test_ledger as fixtures
from research.ssq_dlt_d2_v44.tests.test_ledger import DANS, VERSIONS, NOW, DEADLINE


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography required, no formal admission without it")
class TestPersistentAuthorization(unittest.TestCase):
    register=fixtures.TestLedger.register

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"signed-research.sqlite3"
        self.ledger=Ledger(self.path)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        self.private={role:Ed25519PrivateKey.generate() for role in ("01","04")}
        self.keys={role:{"synthetic-key":key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)}
                   for role,key in self.private.items()}

    def signed(self, issue="SYNTH-01", nonce="synthetic-nonce-0001"):
        value=dict(game="SSQ",issue=issue,slot="M04",version=VERSIONS["M04"],dans=DANS,scope="RESEARCH_ONLY")
        envelopes={}
        for role,key in self.private.items():
            claims=dict(schema="ssq-dlt-auth-v1",role=role,key_id="synthetic-key",payload_sha256=digest(value),
                        nonce=nonce,issued_at=NOW,expires_at="2026-01-01T12:00:00Z",cutoff=DEADLINE)
            envelopes[role]=dict(claims=claims,signature=base64.b64encode(key.sign(canonical(claims).encode())).decode())
        return dict(envelopes=envelopes,trusted_keys=self.keys)

    def test_both_nonces_and_candidate_commit_atomically_and_retry_is_noop(self):
        self.register()
        args=("SSQ","SYNTH-01","M04",VERSIONS["M04"],DANS)
        self.assertTrue(self.ledger.freeze(*args,now=NOW,signed_research=self.signed()))
        self.ledger=Ledger(self.path)
        self.assertFalse(self.ledger.freeze(*args,now=NOW,signed_research=self.signed()))
        with self.ledger.connect(readonly=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM authorizations").fetchone()[0],2)

    def test_second_signature_failure_rolls_back_first_nonce_and_candidate(self):
        self.register()
        signed=self.signed()
        signed["envelopes"]["04"]["signature"]=base64.b64encode(bytes(64)).decode()
        with self.assertRaises(AdmissionBlocked):
            self.ledger.freeze("SSQ","SYNTH-01","M04",VERSIONS["M04"],DANS,now=NOW,signed_research=signed)
        with self.ledger.connect(readonly=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM authorizations").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM candidates").fetchone()[0],0)

    def test_valid_resigned_nonce_cannot_be_replayed_for_another_issue_after_restart(self):
        self.register()
        self.ledger.freeze("SSQ","SYNTH-01","M04",VERSIONS["M04"],DANS,now=NOW,signed_research=self.signed())
        self.ledger=Ledger(self.path)
        self.register(issue="SYNTH-02")
        with self.assertRaisesRegex(AdmissionBlocked,"AUTHORIZATION_REPLAY"):
            self.ledger.freeze("SSQ","SYNTH-02","M04",VERSIONS["M04"],DANS,now=NOW,signed_research=self.signed("SYNTH-02"))


if __name__=="__main__":
    unittest.main()
