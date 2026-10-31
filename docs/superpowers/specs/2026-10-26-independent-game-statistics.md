# Independent-game SHADOW statistics bridge
Base84df, sole PR467/Issue468. The user requires fixed D2/NULL, complete denominators, CP95/exact/Holm and preservation of failures; independent code audit found V47G reports stop at hit/win/loss counts.

Use the existing advance_game_workspace replayed local per-game scores after every issue in its captured roster is completed. Preserve local_d2_diagnostic and every existing frozen row/outcome/score receipt byte. Add a returned local_d2_statistics report using unchanged statistics.evaluate_shadow_d2 and the exact original V47-{game}-{model} twelve-item mapping. Include only this game's complete roster; the other game's six p=1/no-row results are explicitly report placeholders, never its actual sample counts. Do not wait for the other game's unrelated schedule.

Alternatives: a new statistical engine or six-item family would change established arithmetic or multiplicity. A whole new dual-game coordinator would couple independent calendars. Reusing the existing twelve-item arithmetic gives a conservative single-game diagnostic, as independently reviewed; it does not verify preregistration or repeated-look stopping.

The report states THIS_GAME_ONLY, included game, roster/rows hash, as-read identities, another game NOT_INCLUDED_REAL_DENOMINATOR_NOT_VERIFIED, pointwise CI not simultaneous intervals, and repeated-look/official evidence not verified. Add paired rate difference (wins-losses)/N only to this returned analysis. Do not modify saved score receipts/hashes. No statistical report when any local frozen issue is pending. A concurrent later freeze is outside this read scope; existing outer operational coverage warning remains authoritative. A0/NO_EDGE is unchanged.

