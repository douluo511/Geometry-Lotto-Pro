"""Admission boundary, not a trusted timestamp or official-source verifier."""


def admission(untrusted_evidence=None):
    """Local hashes/booleans are not proof. No trusted verifier is configured.

    #481's two-centre consensus and shadow scores may be inspected locally;
    they do not authenticate the target sales cutoff or an independent predraw
    timestamp. Deliberately no caller flag, CLI bypass or auto-promotion path.
    """
    return dict(status='BLOCKED',formal_A=0,edge='NO_EDGE',eligible_predictions=0,
        missing_verifiers=['independently authenticated official result and target',
                           'authoritative sales cutoff',
                           'independent predraw timestamp bound to model and ticket',
                           'prospective complete cohort and independent review'],
        caller_assertions_accepted=False)
