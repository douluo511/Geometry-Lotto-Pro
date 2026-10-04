# Legal Philosophy Study System — re-authored evidence-first candidate

This tree is a **new implementation with a new acceptance lineage**. It does not inherit acceptance from the historical `Law_Philosophy_Principles.exe` candidate.

## Frozen purpose

Turn legal/philosophical study into a traceable judgment workflow for law, rights, society, state, freedom and institutions. It is not an e-book shell, not a stance generator, and not individualized legal advice.

The restored content scope is:

- Preface / Introduction
- Abstract Right: property / contract / wrong
- Morality
- Family
- Civil Society: needs, division of labour, poverty, administration of justice, public administration
- State
- International Law
- World History

Every study result must keep these layers distinct:

1. primary/original text,
2. authoritative scholarship,
3. legal/institutional authority,
4. historical or modern case,
5. model/rule-based inference,
6. user judgment.

## Architecture

Product/Governance → Domain → Source → NetClient → Storage → Engine → Validation → Evidence → Service → UI → Release.

Desktop entries remain:

核心研习 | 一键更新 | 一键修复 | 高级分析

## Current production-source boundary

The first re-authored network chain intentionally starts with sources that can be independently verified now:

- Stanford Encyclopedia of Philosophy: Hegel social/political philosophy — authoritative scholarship.
- Internet Encyclopedia of Philosophy: Hegel social/political thought — independent scholarship used for explicit conflict/tension preservation.
- United Nations: Universal Declaration of Human Rights — official international legal/institutional authority.
- U.S. National Archives: Brown v. Board of Education — validated archival case source.
- U.S. Reports / Library of Congress: Plessy v. Ferguson (1896), West Virginia State Board of Education v. Barnette (1943), and Obergefell v. Hodges (2015).

The current runtime binds every admitted source to a fresh HTTPS receipt, payload hash, semantic markers and canonical-text hash. Two independent scholarship sources are required before source-conflict handling can PASS, and their disagreement is preserved rather than auto-resolved. The case boundary requires the full four-source Plessy/Barnette/Brown/Obergefell corpus so a single famous case cannot manufacture a business PASS.

A helper for identifying an 1896 English edition/scan exists, but edition/section-level primary-text lineage is **not yet integrated into the production evidence chain**. Metadata or scan identity alone does not satisfy the frozen primary-source business gate.

No network or candidate workflow success may be promoted to Final while repository independence, real Release N→N+1, formal re-download Same Hash, or any frozen business gate remains non-PASS.
