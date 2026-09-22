# Go-Trafilatura Recommendation Evaluation

Date: 2026-09-19. Local, uncommitted investigation. The experiment itself did not
change production source; the subsequent integration is recorded separately below.

## Implementation Status

After the study, author whitespace normalization (M3) was applied to the local Go
development source with user approval. Its production/module files match the
measured `M3-normalized-authors` variant; 14 new author regressions and six explicit
Go expectations were added without changing the independent Python fixture. The
Windows Go 1.27.1 gate reports 7,363 passing checks, the same eight reviewed fallback
failures, and 42 skips; build and vet pass. No other experimental change was applied,
and nothing was committed or pushed.

The predictions, source snapshots, and numbers below remain the original study
record. In this report, "current" means the frozen pre-M3 baseline, not the source
after integration. No additional corpus or timing run was used for this integration.

## Recommendation

At study completion, the expanded tests supported these recommendations:

1. **Keep C4 and X11**, the two restored Go safeguards, and **U1**, the whole-line
  filter. Their benefits extend beyond LegoNews. Keep live extraction traversal;
  replacing it with snapshots slightly worsens the two new corpora.
2. **Leave S3 narrow for now.** Broadening it helps two corpora but causes three
  large WCXB failures. This is a real trade-off, not a universally better selector.
3. **Recommend restoring M3 author whitespace normalization for quality**, subject
  to accepting a deliberate metadata divergence from Python. It adds 17 exact
  development matches with no lost exact matches or changed text/title/date.
  Held-out author improvement remains unproven because the affected test pages
  have no author labels.
4. **Reopen X10's extraction decision, not the whole alignment.** Correct subtree
  ownership helps some articles but exposes substantial product/service losses.
  A blanket rollback has its own losses. The decision around that measurement
  deserves a general fix with these new cases as regressions, not a site exception.
5. **Do not call every text-preservation or restrictive rule an F1 improvement.**
  Keep correctness-driven text/tail representation work unless there is a sound
  replacement, but distinguish it from demonstrated quality gains. C5 cascading
  empty-node pruning is a promising small follow-up; the other tiny or neutral
  policy relaxations do not justify a blanket rollback.

These recommendations were not applied during the experiment. The subsequent M3
integration is described above; the other candidate changes remain unapplied.

## Question And Design

Evaluate the recommendation to keep demonstrated fixes and text-preservation work,
investigate S3, and scrutinize restrictive Python-compatibility rules individually.
Python fidelity and extraction quality are separate criteria in this report.

The baseline is the frozen pre-M3 v2 worktree, not this repository's historical v1 adapter
and not the alignment checkpoint alone. It includes complete cleaning, final-body
decision text, and automatic language metadata.

- Source HEAD: `ed2b4c86a5727110178172cb18080efe98fdcdb2`, plus the frozen dirty worktree.
- Source manifest SHA-256: `750c0bd7c569213c939b572af84964b34d0f11e997498c3facd14fa763f3d326`.
- Go module and checksum files are unchanged across variants; Go toolchain 1.27.1.
- Every variant is built in an ignored source copy. No production extractor edits.
- 27 independently changed variants were measured: 23 with comments off and four
  with comments on. Including baselines, an unchanged repeat, native-fallback
  validation, and the held-out pair, there are 34 complete evaluation reports.
- Serial, quality-only runs; no timing measurements or Python extraction bridge.
- Main profile: balanced, native fallbacks off, comments off, tables on, images/links
  off, deduplication off, no target-language restriction. Existing baseline/recall
  recovery remains active. This is not a new minimal-core implementation.
- Development: LegoNews 983, ScrapingHub 181, WCXB 1,495 deduplicated development
  pages. Failures are empty predictions and remain in the denominators.
- All original source attribution, archive pins, annotations, and scoring rules
  remain those in [README.md](README.md) and [benchmarks.json](benchmarks.json).
- The 372 non-overlapping WCXB test pages are reserved for a preselected candidate,
  not used to search for better rules. They are not guaranteed domain-disjoint.

Text F1 means three different published metrics. Do not average their numbers.
Metadata uses only supplied, nonempty annotations; unknown authors are not negative
labels. Author exact match compares normalized sets of the supplied author units,
not inferred individual identities or fuzzy name matches.

## Baseline

| Evaluation | Current Go |
|---|---:|
| LegoNews text F1 | 90.88412% |
| ScrapingHub text F1 | 96.15663% |
| WCXB development text F1 | 78.49352% |
| Author exact match, 1,290 annotated pages | 52.55814% |
| Author micro F1 | 57.43216% |
| Title exact match, 2,364 annotated pages | 51.94585% |
| Date exact match, 1,530 annotated pages | 80.19608% |

Core extraction errors: LegoNews 3, ScrapingHub 0, WCXB development 10. An unchanged
repeat had identical body text and normalized scored metadata on all 2,659 pages.

## Demonstrated Fixes

These are independent counterfactuals against current Go, not cumulative rollbacks.
Numbers are **the benefit of keeping the current fix**, in percentage points of F1.

| Fix retained | LegoNews | ScrapingHub | WCXB dev | Reading |
|---|---:|---:|---:|---|
| C4: remove every unwanted cleaning node | +0.07182 | 0 | +0.05880 | Keep |
| X11: measure decision text after cleanup | +0.02501 | 0 | +0.01528 | Keep |
| U1: filter whole boilerplate lines | +0.01874 | 0 | +0.01216 | Keep |
| X10: measure paragraphs on the selected subtree's owner | +0.01560 | +0.03267 | -0.36365 | Mixed; not an unconditional quality win |

The two safeguards remain supported beyond LegoNews. X10 is a faithful ownership
fix, but the broader quality recommendation must acknowledge its WCXB loss.
Correctness of the measurement does not itself establish the best extraction
decision on every kind of page.

Removing C4 worsens two scored LegoNews pages and seven WCXB pages, with no page-F1
improvements. Removing X11 worsens one scored page in each of those corpora, also
without improvements. Their independent effects need not add linearly.

Removing X10 changes 49 WCXB outputs: 21 improve and 28 worsen, but the larger gains
raise the average. The effect is +3.57747 points on product pages and +0.49279 on
service pages, versus -0.11842 on forum pages. Eight changed Steam pages contribute
about 0.30 of the overall +0.36365 points. On the Dota 2 page, the current 215-character
copyright/footer output becomes 4,144 characters of product content in the rollback.
The rollback also worsens five ScrapingHub articles and reintroduces an unwanted
LegoNews shopping-cart notice. This is evidence to investigate the decision, not
proof that measuring the wrong tree is the right general solution.

## S3 And Restrictive Selectors

Here positive numbers mean **the experimental relaxation improves current Go**.

| Experiment | LegoNews delta | ScrapingHub delta | WCXB dev delta |
|---|---:|---:|---:|
| S3: broaden `article ` prefix to `article` | +0.04995 | +0.10458 | -0.14286 |
| S1: normalize content-selector attribute whitespace | 0 | +0.02816 | +0.00445 |
| S2: restore former case-insensitive content checks | 0 | 0 | +0.00081 |
| S4: normalize direct discard-rule attributes | 0 | 0 | 0 |
| S4: restore former case-insensitive discard checks | 0 | 0 | +0.00191 |
| S4: check either ID/class for cookie | 0 | 0 | 0 |
| S4: check either ID/class for reply prefix | 0 | 0 | 0 |
| S4: check either ID/style for hidden | 0 | 0 | -0.02081 |
| S6: restore case-insensitive comment removal | 0 | 0 | 0 |
| S9: restore full case folding for teaser checks | 0 | 0 | 0 |
| C1: restore structured JSON forum detection | 0 | 0 | 0 |

S3 changes 16 LegoNews, seven ScrapingHub, and 17 WCXB outputs. It improves 11 WCXB
page scores but worsens three much more substantially: Public Domain Review's
coffee article becomes a donation request, a FlyerTalk trip report becomes unrelated
news links, and a personal backup-strategy article becomes blog recommendations.
It restores the KulturKaufhaus article but loses wanted headings on Rutgers/EKHN.
Retaining the narrower Python rule is therefore a reasonable default.

S1's small WCXB net gain hides one improving and one worsening page. S2 changes
only three WCXB texts; the S4 case relaxation changes one. Tiny or zero aggregate
differences do not establish the best rule on unseen pages.

### Text Representation And Preparation

Each row again means **variant minus current Go**, in F1 percentage points.
These are targeted representation probes with current handlers, not complete
reversions of every coupled handler to the old implementation.

| Experiment | LegoNews delta | ScrapingHub delta | WCXB dev delta |
|---|---:|---:|---:|
| C5: cascade removal of newly empty parents | 0 | +0.00130 | +0.02137 |
| C8: restore ul/ol/dl link-protection ancestors | 0 | 0 | 0 |
| D1: collapse explicit empty text/tail slots to absent | 0 | 0 | 0 |
| D2: snapshot instead of live extraction traversal | 0 | -0.00725 | -0.00322 |
| D2: clone-based instead of identity-preserving unwrapping | 0 | 0 | 0 |
| D3: normalize whitespace in decision text | 0 | 0 | 0 |
| X4: stop copying heading/code clone tails | 0 | 0 | +0.02791 |

C5 improves one ScrapingHub page and five WCXB pages without measured page-F1 losses.
Most of its small WCXB gain comes from one Eventbrite listing. It is a candidate for
a focused follow-up, not a reason to undo the separate complete-cleaning safeguard.

Removing clone-tail preservation improves nine WCXB pages and worsens 19; its net
gain is dominated by one Salesforce page. The paired interval includes no effect.
Dropping text that belongs to an element is not justified by that aggregate alone.
The expanded corpus does not prove every slot/tail change improves F1.

### Comments-Enabled Checks

The four independent S5/S7 probes normalize comment attributes or inspect both
attributes instead of only the first source-order attribute. All four leave body
text and scored metadata unchanged against the comments-enabled baseline. That
baseline's text F1 is 90.82474%, 96.00020%, and 78.51691%, respectively.

S5's either-attribute selection changes seven separate comment outputs; the other
three probes change none. There are no gold comment-text labels, so these changes
cannot be scored as comment-quality improvements. Corrected Disqus spelling and
Go quote-tag mapping were preserved rather than bundled into these policy tests.

## Metadata

M3 normalizes only the ID/class values used in author selection and author-node
discarding. It does not change JSON-LD parsing, meta-tag parsing, title/date rules,
or the language classifier.

On development inputs, this raises author exact match from **678/1,290 to 695/1,290**
(52.55814% to 53.87597%) and author micro F1 from **57.43216% to 58.80923%**.
All three text F1 scores are unchanged. This is a stronger measured reason to relax
a restriction than the small content-selector movements above.

| Corpus | Author labels | Current exact | M3 normalized exact | Current author F1 | M3 author F1 |
|---|---:|---:|---:|---:|---:|
| LegoNews | 552 | 279 (50.54348%) | 281 (50.90580%) | 56.06061% | 56.33270% |
| WCXB development | 738 | 399 (54.06504%) | 414 (56.09756%) | 58.45718% | 60.66619% |
| WCXB held-out test | 133 | 88 (66.16541%) | 88 (66.16541%) | 69.23077% | 69.23077% |

The 23 changed development authors comprise 17 new exact matches, zero lost exact
matches, and six still-wrong results. Gains are forum usernames/bylines across
multiple domains. The two LegoNews recoveries are Tiberius and Pepemaus; WCXB adds
15 correct authors. Some remaining mistakes strip digits or punctuation from
usernames, which M3 does not fix. Titles, dates, and language values are unchanged.

### Held-Out Result

Only M3 was selected before any test extraction, recorded in
[.cache/recommendation-study/holdout-plan.json](.cache/recommendation-study/holdout-plan.json).
No other rule was tuned or selected using test results.

On the 372 cleaned WCXB test pages, body text is identical, F1 remains **82.57221%**,
and both variants have two errors. The 133 annotated authors, 370 annotated titles,
and 192 annotated dates are unchanged. M3 changes 13 author outputs, but **all 13
are unannotated**. Some are forum index pages, so a nonempty username should not
automatically be considered a correct page author.

The runner also repeats LegoNews and ScrapingHub as controls in its test profile.
Its combined metadata total therefore contains the two already-known LegoNews
improvements. Those are **not held-out gains**. The held-out result establishes no
observed scored regression, but cannot confirm the forum-author improvement.

### Native Go Fallback Validation

Current and M3-normalized builds produce identical body text with native fallbacks
enabled. F1 is **90.97104% LegoNews, 96.46707% ScrapingHub, 82.97929% WCXB dev**.
M3 again adds 17 exact development author matches, with unchanged title/date values.
The fallback code, candidates, order, acceptance, sanitization, lazy stopping, and
recall rescue were not edited. This is validation of M3 in that workflow, not a
separate ablation of each fallback algorithm.

## Uncertainty And Scope

Paired page resampling uses 2,000 deterministic bootstrap samples (seed 20260919),
recomputing each corpus's actual aggregate. These exploratory 95% percentile
intervals are neither multiple-testing-adjusted nor domain-clustered.

| Variant minus current | LegoNews interval, points | ScrapingHub interval, points | WCXB dev interval, points |
|---|---:|---:|---:|
| S3 broadened | [-0.05822, +0.20037] | [-0.09485, +0.38499] | [-0.35375, +0.01784] |
| X10 removed | [-0.04715, 0] | [-0.07314, -0.00486] | [+0.12573, +0.67591] |

Page-type and domain concentration matter: eight Steam pages are not eight
independent site designs. None of these results establish arbitrary-input Python
parity or a universal ranking of selectors. This investigation did not retune
thresholds, test all combinations, or change reference labels. Precision/recall
focus, image/link/dedup options, language accuracy, and dependency/backend upgrades
were not independently benchmarked. Neutral probes must not be read as validation
of every associated path.

The current source passed focused complete-cleaning, post-cleanup decision-text,
duplicate recovery, mixed-content, and image-tail tests. Removing C4 or X11 makes
its corresponding regression tests fail as expected. All 22 existing benchmark
metric, preparation, and prediction-provenance tests pass, including comparisons
with the pinned ScrapingHub and WCXB scorers. Both production copies' 64 Go/module
files still match the frozen hashes. The existing full production gate was not
rerun; its previously reviewed fallback failures are not resolved or reclassified
by this study.

## Evidence Files

The current experiment artifacts are intentionally local and ignored:

- [.cache/recommendation-study/source.json](.cache/recommendation-study/source.json):
  exact HEAD, dirty source diff, and per-file hashes.
- [.cache/recommendation-study/variants.json](.cache/recommendation-study/variants.json):
  named counterfactuals and exact, count-checked replacements.
- [.cache/recommendation-study/adapter.go](.cache/recommendation-study/adapter.go):
  current-v2 JSONL adapter; no reference labels are passed to extraction.
- [.cache/recommendation-study/study.py](.cache/recommendation-study/study.py):
  source freezing, isolated builds, input checks, and scoring.
- [.cache/recommendation-study/analyze.py](.cache/recommendation-study/analyze.py):
  paired page analysis and exploratory bootstrap intervals.
- [results/recommendation-study-2026-09-19](results/recommendation-study-2026-09-19):
  per-build hashes/patches, full predictions, evaluations, and paired analyses.

For each evaluation, `*-predictions.json` retains every output/error and
`*-evaluation.json` retains per-page metrics. The `analysis-current-*.json` files
contain changed page IDs/URLs, both scores, metadata before/after/reference values,
page-type breakdowns, and intervals. No failed or neutral variant is suppressed.

To reproduce an existing development comparison from this prepared checkout:

```powershell
python .cache/recommendation-study/study.py --variants current S3-broad-article
python .cache/recommendation-study/analyze.py --variants S3-broad-article --inspect
```

Use the recorded Python environment with NumPy for analysis. The extractor itself
is the isolated native Go binary. Study scripts, source snapshots, and large outputs
are local ignored evidence, not a published release. The WCXB test set has now been
consumed for the one predeclared M3 comparison and must not be described as unseen
in subsequent tuning.