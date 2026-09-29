# Documentation and Release Maintenance

These instructions are for LLM agents and human maintainers. Read them before
changing benchmark claims, README.md, UPSTREAM.md, CHANGELOG.md, release notes,
or package documentation in the extractor family. Explicit user instructions
take precedence; stop and ask when they conflict with a publication constraint.

## Repository Family

This repository owns the shared comparison of six implementations:

| Engine | Go Repository | Rust Repository | Rust Crate |
| --- | --- | --- | --- |
| DomDistiller | go-domdistiller | rust-domdistiller | rust-domdistiller |
| Mozilla Readability | go-readabilityV2 | rust-readability | rust-readability-v2 |
| Trafilatura | go-trafilatura | rust-trafilatura | rust-trafilatura |

All repositories are under github.com/markusmobius. The application workers in
newsprinceton-gopython are separate consumers, not the subject of library docs.

## Document Responsibilities

- README.md answers what was compared, how to read the results, and how to
  reproduce the benchmark. Put the newest completed results first under
  `## Results: YYYY-MM-DD`; label previous results historical.
- Library README.md files explain purpose, scope, usage and current tradeoffs.
  Prefer the Go-Trafilatura structure when aligning its Rust counterpart. Keep
  readable library documentation separate from detailed investigation logs.
- Library UPSTREAM.md files hold source pins, compatibility differences,
  methodology, exact hashes, test coverage and verification limitations.
- Library CHANGELOG.md files describe user-visible changes and their reasons
  by version. Do not paste a benchmark report or a worker incident history.
- This repository currently uses dated README sections and immutable reports
  instead of UPSTREAM.md and CHANGELOG.md. Do not create empty companion files
  merely to make its layout resemble a library. If added later, use these roles.
- GitHub release notes summarize the same changes as the corresponding
  changelog and use the same benchmark definitions as the README.
- Crates.io README content comes from the published crate archive, not the
  latest GitHub README. Publication must be planned after documentation is final.

## Shared Benchmark Format

All six library READMEs must have a `## Current Quality and Speed` section.
Use one common six-implementation speed table, not six unrelated selections:

| Extractor | Go Version | Rust Version | Go ms/page | Rust ms/page | Go/Rust |
| --- | --- | --- | ---: | ---: | ---: |
| Readability | measured version | measured version | measured mean | measured mean | ratio |
| DomDistiller | measured version | measured version | measured mean | measured mean | ratio |
| Trafilatura FAST | measured version | measured version | measured mean | measured mean | ratio |

1. Select one completed shared-suite report from this repository for all three
	rows and all six READMEs. Use immutable commit links to its JSON and README.
	Never mix dates, machines, modes, hardware states or timing boundaries.
2. Copy values from the structured report, not prose or memory. For the current
	protocol use means of all four measured passes after one warmup. Recompute
	aggregates from retained samples when validating a new report. Do not select
	the fastest pass, silently discard outliers, or mix means with medians.
3. Show extraction time in milliseconds per page to three decimal places.
	Compute Go/Rust from unrounded values and display two decimals plus `x`.
	A ratio is a within-run language comparison, not an old/new version speedup.
4. Name the actual measured versions. A documentation-only patch is not a new
	benchmark. Retain the old measured version labels and explain the absence of
	runtime changes; never claim that an unmeasured version was timed.
5. Report parsing separately, charged once per language/page in the shared
	suite. Include decoding, normalization, DOM construction and any separate
	Trafilatura noscript tree in the stated parsing boundary. Do not hide work
	in setup or add the shared parse cost once per engine.
6. State corpus names/counts, hardware, OS, toolchains, allocator/build profile,
	warmup/pass counts, relevant options, and included/excluded work once in
	concise common prose. The report keeps the full provenance.
7. Put non-FAST Trafilatura results in a separately identified comparison from
	its own report. Do not blend that run with the FAST six-engine table or use
	cross-run absolute times to infer a fallback overhead or release speedup.
8. Keep text quality distinct from speed. Use named corpora and their own F1
	definitions; do not average scores with different scoring rules. Record
	errors in the denominators. Display percentages consistently to five decimal
	places and link the complete scoring report.
9. Matching text scores do not prove matching HTML or metadata. State known
	output differences. Score metadata only where annotations exist; an absent
	annotation is not a negative label.
10. Do not pool the annotated quality suite with the separate unannotated
	 fallback corpus. A fallback selection rate is not an accuracy/error rate.

Keep historical tables explicitly dated. Old standalone/102-pass measurements
and new shared-input measurements have different boundaries and are not a
controlled speedup experiment. Move detail to technical references rather than
filling the current section with competing historical headline numbers.

## Trafilatura Explanation

- FAST disables external fallback. Native recall and baseline recovery can
  still run. Non-FAST permits only internally generated bundled readability-lxml.
- Mozilla Readability and DomDistiller are independent extractors. Removing
  their use as Trafilatura fallback candidates does not remove their standalone
  APIs or any application's independently requested extraction.
- Explain why supplied candidates were removed: candidates extracted before
  Trafilatura's input cleanup can retain long boilerplate that passes its length
  checks and replaces article content. Do not say the other extractors perform
  no cleaning; the difference is which prepared input reaches them.
- The historical same-version Go 2.2.2 control selected external fallback on
  780/6,554 pages (11.90%) with internally generated candidates versus
  2,408/6,554 (36.74%) with supplied candidates; DomDistiller accounted for
  4 versus 1,614 selections. Label these historical controlled measurements.
- The 2.2.6 lxml-only policy returned external fallback on 202/6,554 (3.08%).
  That policy also changes the fallback algorithm set, so the entire reduction
  from 36.74% is not attributable to candidate removal alone. Python's jusText
  is not DomDistiller, and Mozilla Readability is not bundled readability-lxml.
- Count the source of final returned content, not calls or temporary candidate
  acceptance. Keep failures in the denominator and report internal recovery
  separately. A lower rate does not establish higher quality.
- Library changelogs must not mention rustHTML. Keep application protocol,
  deployment, flag matrices and integration incidents out of library README
  benchmark summaries and release notes. Detailed evidence may remain linked.

## New Measurements

1. Confirm the requested modes, corpus, run count and acceptance criteria before
	a long run. Do not silently expand an approved run budget or start a new
	optimization campaign for a documentation task.
2. Freeze the measured source, dependency graph, options, binaries and corpus.
	Record their identities before timing. Do not edit measured inputs mid-run.
3. Warm the page cache consistently and interleave compared configurations.
	Record power and sleep/resume events. Sleep or systematic order drift can
	invalidate timing even if all samples completed; preserve and label them.
4. Retain every raw sample. Separate scored output equality, metadata
	differences, timing validity and engine-selection tracing as distinct checks.
5. Publish a new dated report only after checking arithmetic, completeness,
	source identities and timing boundaries. Never rewrite an old report to
	describe a newly corrected implementation.
6. Hash the exact committed/published bytes. Windows CRLF checkout hashes can
	differ from Git's LF bytes; verify staged blobs and the immutable remote
	response before placing checksums in documentation.

## Documentation and Publication Workflow

1. Read current files and git status in each affected repository. Preserve
	unrelated work. Check existing maintenance instructions before editing.
2. Decide whether this is a new measurement, a runtime release, or documentation
	only. Do not rerun benchmarks for wording changes. Do not change extraction
	behavior to make a prose claim true.
3. Update the benchmark repository's current results and all six library
	benchmark sections from the same reports. Keep the common table and wording
	synchronized; preserve useful language-specific API documentation.
4. Update each affected UPSTREAM with evidence and limitations, each CHANGELOG
	with release-facing changes, and each release body with the same claims.
	Technical receipts belong in UPSTREAM/reports, not repeated across the README.
5. Validate counts, units, rounding, ratios, versions, mode names, Markdown links
	and section equality across all six READMEs. Check documentation examples
	with their existing tests. Run `git diff --check` and review the scoped diff.
6. Obtain explicit authorization before new versions, commits, pushes, tags,
	GitHub releases or registry publication. Never move a published release tag
	or overwrite a crate archive. Crates.io README changes require a new version.
7. For an authorized documentation-only release, keep runtime source and
	dependency pins unchanged. Bump only package identity/lockfile entries and
	finalize README, UPSTREAM, CHANGELOG and agent instructions before packaging.
8. Inspect the packaged archive: README and other intended docs must match the
	release commit, source files must match the declared runtime baseline, and
	no temporary tools/secrets or unintended files may be included. Publish from
	a clean, approved commit, not a dirty working-tree archive.
9. Verify the public artifact checksum and packaged sources/docs after upload.
	A Git tag is not a GitHub release; verify both the release page and normal
	registry/module installation. Preserve release identity when editing an
	existing release body. Do not expose credentials in tools or prose.
10. Report what was changed and actually checked, publication URLs/versions,
	 remaining local work and any unverified platforms. Do not claim a test or
	 hosted CI run passed merely because publication succeeded.

When updating this contract, propagate the corresponding rules to the six
library AGENTS.md files. Keep one root AGENTS.md per repository; do not add
a separate maintenance guide or discovery-only pointer.