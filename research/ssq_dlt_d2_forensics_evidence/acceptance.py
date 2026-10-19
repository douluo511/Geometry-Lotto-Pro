"""Current-byte acceptance including the separate presentation verifier."""
from research.ssq_dlt_d2_forensics import acceptance as frozen_acceptance


def main(argv=None):
    names=tuple(name for name in frozen_acceptance.NAMES if name!='ssq_dlt_d2_forensics_evidence')
    frozen_acceptance.NAMES=names+('ssq_dlt_d2_forensics_evidence',)
    return frozen_acceptance.main(argv)


if __name__=='__main__':raise SystemExit(main())
