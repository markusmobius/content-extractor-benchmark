# Content Extractor Benchmark

Four independent, reproducible quality evaluations plus configurable speed and memory comparisons for content extractors. Any language can participate through saved JSON predictions or a serial JSON-lines adapter. Scores are not combined across benchmarks.

## Standard Benchmarks

| Evaluation | Source Records | Default Evaluation | Main Score |
| --- | ---: | --- | --- |
| **LegoNews** | 983 | All 983 original pages | Case-sensitive wanted/unwanted snippet micro F1 |
| **ScrapingHub** | 181 | All 181 article pages | Four-word shingle F1 from mean per-page precision and recall |
| **WCXB** | 2,008 | 1,495 distinct development pages; separately, 372 test pages without known overlap | Mean per-page word-multiset F1, also reported by page type |
| **Metadata** | Available annotations from LegoNews and WCXB | Same selected inputs, scored only on annotated fields | Exact author-set match, author-unit micro F1, title/date exact match |

LegoNews is our name for the existing benchmark, not a new corpus. Its code and fixtures were adapted from the [Go-Trafilatura comparison](https://github.com/markusmobius/go-trafilatura); the [original 983-page snapshot](https://github.com/markusmobius/content-extractor-benchmark/tree/466fdbee8a504441eb78ed11d71c1da220681cab) remains the reference. Its original case-sensitive snippet score is preserved.

ScrapingHub comes from [scrapinghub/article-extraction-benchmark](https://github.com/scrapinghub/article-extraction-benchmark), using its complete article-body annotations and scoring rules. WCXB comes from [Murrough Foley's Web Content Extraction Benchmark](https://webcontentextraction.org/benchmark/), with [source and annotations](https://github.com/Murrough-Foley/web-content-extraction-benchmark) and [DOI 10.5281/zenodo.19316874](https://doi.org/10.5281/zenodo.19316874). Original annotations are retained, not generated from extractor outputs.

Exact source commits, archive SHA-256 values, source links, and licenses are pinned in [benchmarks.json](benchmarks.json). Preparation retains the downloaded source notices and evaluators in the ignored local cache. Changes to benchmark inputs require an explicit registry update, not a silent refresh from upstream `main`.

### Test Provenance

These are saved-page evaluations, not live website crawls. Preparation decompresses the upstream HTML without decoding or rewriting it, copies the supplied annotations into a common manifest, and hashes both. Extractors receive only an ID, URL, and original HTML file path; labels and page types are never sent to them.

| Source | Pinned Snapshot | Annotation Origin And Limits |
| --- | --- | --- |
| LegoNews | [466fdbee](https://github.com/markusmobius/content-extractor-benchmark/tree/466fdbee8a504441eb78ed11d71c1da220681cab) | The original 983-page Go content-extractor comparison, adapted from Go-Trafilatura. Supplied `with`/`without` snippets test selected content and boilerplate, not complete article boundaries. The upstream comparison credits the BBAW collection, tsolewski's Polish news collection, and diskursmonitor.de. The snapshot does not establish a random or representative sample of the web. |
| ScrapingHub / Zyte | [4a3bc979](https://github.com/scrapinghub/article-extraction-benchmark/tree/4a3bc979f76c0df73cb95fe272e2fc1b96f9f010) | All 181 supplied `articleBody` references from the article-extraction benchmark introduced in 2019. Its README describes HTML captured with Splash, JavaScript disabled by default. This harness uses those saved files and the upstream four-word scoring rule, not its historical leaderboard outputs. No author/title/date ground truth is supplied. |
| WCXB, Murrough Foley | [c039d5ee](https://github.com/Murrough-Foley/web-content-extraction-benchmark/tree/c039d5ee9f5a3a984a0e167e63aacd04e76e78a9) | Seven page types with complete `main_content` and optional metadata. Upstream describes LLM-assisted drafting, four human review passes, automated checks, and re-review of low-scoring pages. These are externally supplied references, not an independent human-only gold standard. The development split is used in the release battery; no unseen-test claim is made. |

The corpus licenses are Apache-2.0, MIT, and CC-BY-4.0 respectively; publisher rights to the saved pages remain separate. Source archives are downloaded locally, not fetched during extraction. Original notices, archive checksums, prepared-record checksums, and every HTML checksum remain available for audit. The dated result JSON embeds the pinned source descriptions, annotation provenance, and selected input hashes. Labels are never regenerated from a candidate extractor.

### Corpus Independence

The pinned WCXB release has 1,497 development and 511 test records. Decompressed HTML hashes reveal two development duplicates and 139 test pages identical to development pages: **1,867 distinct HTML inputs**, not 2,008 independent pages. The default excludes these later duplicates. `--upstream-records` retains every original record for upstream score comparison; that mode must not be described as an independent holdout.

Preparation records both decompressed HTML hashes and conservative normalized-URL overlaps across all three corpora. Earlier records take precedence: LegoNews, ScrapingHub, WCXB development, then WCXB test. URLs ignore scheme, `www.`, fragments, and trailing slashes, but retain path case and query. This is not semantic near-duplicate detection or a domain-disjoint split. The manifest retains every record and its exclusion reason.

Keep the remaining test subset for final validation. Do not tune extraction rules against its labels or repeatedly use its scores to select changes. WCXB's LLM-assisted, human-reviewed annotations are useful independent references, not infallible truth; disputed cases should be reviewed separately without rewriting labels to fit our extractor.

Holdout use is specific to an experiment, not a permanent property of a filename. Record which candidates have been evaluated on it; after inspecting those results, do not describe the same pages as unseen evidence for further tuning. The [Go-Trafilatura recommendation study](RECOMMENDATION_EVALUATION.md) used the cleaned WCXB test subset only for its predeclared author-normalization comparison.

## Results: 2026-09-21

### Text Quality

[quality_2026_09_21.json](quality_2026_09_21.json) contains the seven-release quality results on all 2,659 development pages. All engines completed one full warmup and four measured passes; the audit checked all 93,065 requests and independently recomputed the scores. These are separate F1 measures, not a combined ranking. Errors are LegoNews / ScrapingHub / WCXB counts and remain in the denominators.

| Implementation | LegoNews F1 | ScrapingHub F1 | WCXB F1 | Errors |
| --- | ---: | ---: | ---: | --- |
| go-trafilatura-2.0.0 | 89.98964% | 95.90278% | 76.83511% | 1 / 1 / 0 |
| go-trafilatura-2.2.2 | 90.88412% | 96.15663% | 78.49352% | 3 / 0 / 10 |
| go-domdistiller-1.0.0 | 86.74080% | 92.45965% | 74.39696% | 0 / 1 / 0 |
| go-readabilityV2-0.6.0 | 87.82711% | 95.20557% | 78.47603% | 7 / 0 / 28 |
| rust-trafilatura-2.2.2 | 90.88412% | 96.15663% | 78.49352% | 3 / 0 / 10 |
| rust-domdistiller-1.0.0 | 86.74080% | 92.74280% | 74.39696% | 0 / 0 / 0 |
| rust-readability-0.6.1 | 87.82711% | 95.20557% | 78.47603% | 7 / 0 / 28 |

Metadata scores remain separate in the JSON, with 1,290 author, 2,364 title, and 1,530 date annotations and per-source breakdowns. The corresponding Go/Rust Trafilatura and Readability releases have matching quality scores. DomDistiller recorded one Go-side ScrapingHub extraction error and no Rust-side errors. Unsupported metadata is left empty, not supplied by another extractor.

### Speed

[performance_2026_09_21.json](performance_2026_09_21.json) reports the **best two of four measured passes** over all 2,659 development pages. Passes 1 and 2 were selected after measurement by the lowest summed request wall time across all seven engines and three corpora. Every row uses the same complete passes, averaging 5,318 page observations. Lower milliseconds per page and higher pages per second are better.

| Implementation | Mean ms/page | Pages/second |
| --- | ---: | ---: |
| go-trafilatura-2.0.0 | 21.614 | 46.27 |
| go-trafilatura-2.2.2 | 20.976 | 47.67 |
| go-domdistiller-1.0.0 | 18.121 | 55.19 |
| go-readabilityV2-0.6.0 | 16.075 | 62.21 |
| rust-trafilatura-2.2.2 | 12.047 | 83.01 |
| rust-domdistiller-1.0.0 | 17.831 | 56.08 |
| rust-readability-0.6.1 | 16.199 | 61.73 |

Pages/second is 1,000 divided by the unrounded mean milliseconds/page. These are best-of-four figures, not the four-pass average. All four pass totals remain in the JSON; `pass_selection` identifies the rounds used for `overall_speed` and the per-corpus `summary`.

The host was Windows 11 on an AMD Ryzen AI 7 PRO 350, using Go 1.27.1 and Rust 1.98.1 with the Windows GNU toolchain. Both summary files carry the same comparison hash, pinned source/build identities, and input selection. Raw predictions and page timing logs are not retained. Nothing from separate runs is pooled.

### Shared-Input Rust Qualification

[rust_shared_performance_2026_09_21.json](rust_shared_performance_2026_09_21.json) records a separate Rust-only paired comparison of Readability 0.6.1 / 0.6.2, DomDistiller 1.0.0 / 1.0.1, and Trafilatura 2.2.2 / 2.2.3. Each persistent worker contains all three engines and parses each page once. These native stage timings are **not comparable to the request-latency table above**.

| Suite | Engine | Shared Parse ms/page | Extraction ms/page |
| --- | --- | ---: | ---: |
| Previous | Readability 0.6.1 | 4.678 | 3.540 |
| Candidate | Readability 0.6.2 | 4.697 | 3.553 |
| Previous | DomDistiller 1.0.0 | 4.678 | 2.920 |
| Candidate | DomDistiller 1.0.1 | 4.697 | 2.917 |
| Previous | Trafilatura 2.2.2 | 4.678 | 5.824 |
| Candidate | Trafilatura 2.2.3 | 4.697 | 5.838 |

The parse column is one shared cost per worker/page, not an additional parse for every engine. It includes in-memory decoding and HTML parsing **after the entire file read completes**. Extraction includes working-tree copies/conversions, native metadata, text rendering and temporary-tree destruction; it excludes file reads, parsing, startup, IPC, JSON serialization and controller scoring. Trafilatura fallback is disabled, with no supplied fallback candidates; comments and DomDistiller pagination are also disabled. No DOM or extraction result is reused across requests.

All 2,659 development pages ran through one full warmup and four measured passes, with matching scored text/metadata/error outputs for every old/new engine pair. Both workers remain alive; worker order is randomized and exactly first/second balanced over four passes for each page. Each pair receives the same randomized engine order. Three engines require six passes for complete per-page position balance, so four is a partial block. Both suites use Rust 1.98.1 Windows GNU, ThinLTO and mimalloc on the same host described above. This compares coordinated library suites, not isolated algorithm changes.

The table uses the same best two complete passes (2 and 3), ranked by summed extraction time across both suites and all three engines. Extraction-time changes are Readability **+0.37%**, DomDistiller **-0.11%**, and Trafilatura **+0.24%**; all-four-pass changes are **+0.78%**, **+0.43%**, and **+0.25%**, respectively. All pass the predeclared 5% regression limit on both means. No sleep events were recorded. Source/build receipts, all pass totals, per-pass ratios, separate quality scores and the 26,590-response audit are retained; raw responses are removed. This is single-machine regression evidence, not a guaranteed speedup.

To reproduce the release comparison from sibling Git checkouts with their tags fetched:

```sh
python tools/build_split_rust.py --sources .. --candidate-ref v2.2.3 --output .cache/rust-split-releases
python split_compare.py --config .cache/rust-split-releases/compare.json --output results/rust-split-releases --runs 4 --best-passes 2
```

The builder archives the requested Trafilatura tags and uses each tag's locked dependency graph; it adds only the common benchmark adapter. Omit `--candidate-ref` to snapshot all three candidate working trees, including local changes. `--offline` requires already cached Cargo dependencies. The measured candidate was a recorded worktree snapshot; release packaging must preserve those runtime file hashes. The new APIs share an immutable input, not a single internal mutable DOM representation. This does not add a Go unified worker or change the production `rustHTML` worker.

## Quick Start

For the released Go/Rust comparison, use Python 3.11+, Git, Go 1.27.1, and Rust 1.98.1 through rustup, with the platform linker installed. Run from this repository's root:

```sh
python -m pip install -r requirements-performance.txt
python run_benchmark.py --runs 4 --best-passes 2
```

[run_benchmark.py](run_benchmark.py) prepares missing corpus data, builds the pinned engines once in `.cache/releases`, then reuses those builds. By default it runs all seven engines on all 2,659 development pages with one full warmup and **N=4 measured passes**. `--best-passes 2` reports the same two fastest complete passes for every engine, as in the table above; omitting the flag reports the average of all measured passes. Progress is printed throughout. Each invocation creates a new timestamped directory under `results/` containing only `quality_YYYY_MM_DD.json` and `performance_YYYY_MM_DD.json`; existing dated results are never overwritten. Raw predictions and page timings are audited and deleted, including on failure or Ctrl+C. Quality-only mode produces just the quality summary.

In this existing Windows checkout, reuse the already installed Python environment and seven release binaries:

```powershell
.\.cache\performance-venv\Scripts\python.exe run_benchmark.py --build-dir .cache/release-suite-2026-09-21 --best-passes 2
```

Useful options (combine with `--build-dir` above when reusing that cache):

```sh
python run_benchmark.py --mode quality
python run_benchmark.py --runs 4 --output results/my-comparison
python run_benchmark.py --limit-per-corpus 3
python run_benchmark.py --scraper go-trafilatura-2.2.2 --scraper rust-trafilatura-2.2.2
python run_benchmark.py --config .cache/releases/compare.json
python run_benchmark.py --list
python run_benchmark.py --help
```

`--limit-per-corpus` is a smoke-test sample, not a full benchmark. `--config` accepts an existing adapter configuration and skips builds. `--build-dir` verifies reused builds against the selected release pins; an incomplete or incompatible cache is rejected. Choose a new build directory to change compiler versions or rebuild. No dependencies are installed automatically, and Rust-Trafilatura still requires access to its private Git repository for a new build.

On Windows, the command finds standard Go/Git/rustup installations and uses the MSYS2 UCRT64 compiler/runtime directory when installed at its standard location. Override paths with `--go`, `--git`, `--cargo`, `--rustc`, and repeatable `--runtime-dir`. The Windows keep-awake request is enabled by default; keep the lid open because this cannot prevent manual suspend. Windows sleep/resume events and power status are recorded as diagnostics outside the measurement timers. No global power settings are changed; battery operation is not an eligibility gate.

### Individual Steps

The underlying commands remain available for manual control:

```sh
python -m pip install -r requirements-performance.txt
python prepare.py
python -B -m unittest discover -p 'test_*.py' -v
python tools/build_releases.py --output .cache/releases-2026-09-21
python compare.py --config .cache/releases-2026-09-21/compare.json --output results/releases-2026-09-21 --mode speed --timing page --runs 4 --warmups 1 --seed 20260921 --publication-date 2026-09-21
python tools/publish_results.py --run results/releases-2026-09-21 --date 2026-09-21 --output results/published-releases-2026-09-21 --discard-raw --best-passes 2
```

The comparison uses temporary predictions and per-page observations for validation. Quality comes from the first full warmup; all four timed passes must reproduce those outputs. The final command independently checks every observation, process ID, schedule, pass total, mean, repeated prediction, and recomputed quality score. It exports just `quality_2026_09_21.json` and `performance_2026_09_21.json`: aggregate scores, all pass totals, diagnostics, source/build provenance, and audit counts. `--best-passes 2` selects the two fastest complete shared passes for reported speed without changing the quality scores or full-run audit. No per-page predictions, timing logs, or evidence archive are published. With `--discard-raw`, it removes the raw run directory only after both summaries have been written successfully.

Reproductions use a new export directory outside the run directory so they cannot replace the checked-in results or delete their own summaries. To prepare a new dated publication at the repository root, use an unused date and `--output .`. The command performs no Git commit or network upload and refuses to overwrite existing dated results. The retained hashes identify the audited transient data; they are not download links for raw data. The pinned inputs, adapter sources, and commands support a fresh reproduction.

To run quality without measuring speed, use `--mode quality` with a new output directory; the exporter audits and writes only the quality summary. The quality-only `benchmark.py` harness also remains available without third-party Python dependencies.

Consumers can read `quality[ENGINE].evaluations[CORPUS].overall.f1` in the quality file and `overall_speed[ENGINE].mean_ms_per_page` in the performance file. F1 values are fractions, not percentages. Both files carry the same `comparison_sha256`, source identities, input selection, and build identities; match these before comparing rows. For durable references from an extractor README, link to these files at a specific benchmark repository commit rather than relying on a mutable branch. Do not mix the quality from one run with the timing or binaries from another.

For best-of-N reports, `pass_selection` records the ranking rule, selected rounds, and reported pass count. The original measured count, every pass total, and the full-run audit remain available. Selected means include every page in each chosen pass, with no per-engine pass selection or within-pass filtering.

On Windows, `--rust-toolchain 1.98.1-x86_64-pc-windows-gnu` selects the GNU Rust target; its GCC linker and runtime DLL directory must be on `PATH` (or set `CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER`). The native MSVC toolchain is also supported when installed. Add `--keep-awake` to the comparison command to temporarily request Windows system/display wakefulness and restore the previous execution state afterward. It does not change the global power plan or prevent manual suspend. Power status is recorded, not an AC-only eligibility gate.

### Release Battery

[release-suite.json](release-suite.json) pins the exact Git tags and peeled commits for seven independently built executables:

| Implementation | Releases | Profile |
| --- | --- | --- |
| Go-Trafilatura | 2.0.0 and 2.2.2 | Balanced, core-only, comments off, tables on, automatic native metadata |
| Go-DomDistiller | 1.0.0 | Standalone, pagination off |
| Go-ReadabilityV2 | 0.6.0 | Default reader/parser and native metadata |
| Rust-Trafilatura | 2.2.2 | Same Trafilatura options as Go |
| Rust-DomDistiller | 1.0.0 | Standalone, pagination off |
| Rust-Readability | 0.6.1 | Default reader/parser and native metadata; package name `rust-readability-v2` |

[tools/build_releases.py](tools/build_releases.py) clones each tag into a new cache directory, verifies its commit, and builds against that release's own unchanged dependency lock. No sibling worktrees, dependency upgrades, module-path rewrites, or library patches are used. Go-Trafilatura 2.0.0 uses the historical module path without `/v2`; only its adapter import differs. It also uses older language/date/parser dependencies, so comparison with 2.2.2 measures the complete release, not an isolated core-code change.

Go builds use the same compiler, CGO disabled, `GOMAXPROCS=1`, `-trimpath`, and `-pgo=off`. Rust uses each release's shipped release profile and default features: Trafilatura's executable installs its default mimalloc; Readability and DomDistiller use their default allocator. No CPU-native flags or PGO are added. Build receipts contain full dependency graphs, source and lockfile hashes, adapter hashes, exact commands, compiler versions, and executable hashes; they are embedded in the exported JSON. Each Rust adapter is built within its own package graph, not a combined workspace that unifies dependencies.

Every request reads and decodes its original HTML, parses it, extracts content and native metadata, renders plain text, and serializes one response. No HTTP acquisition, browser rendering, cross-request result cache, or extraction worker pool is introduced. Readability dates use its native publication-time API, with UTC for timestamps lacking a zone; explicit offsets retain their calendar date. DomDistiller does not borrow an author/date extractor. Date/language work differs between algorithm families and is part of the measured native pipeline, not artificially equalized.

Rust-Trafilatura's repository is private at the time of this battery; reproducing that row requires Git access. This harness does not change repository visibility or publish private source. Select accessible subsets with repeated `--scraper NAME` on the builder and runner, but do not present a subset as the complete seven-engine battery.

The release battery uses all **2,659 development pages**, one complete warmup, and **N=4 complete measured passes per engine**: 10,636 timed observations per row and 74,452 across seven rows. Best-two reporting uses 5,318 observations per engine and retains all four pass totals. All engines stay alive together and process each page serially in seeded randomized order. Seven engines need 14 passes for exact per-page position balance under this schedule; N=4 is a reproducible partial block, not perfectly balanced. The actual order, process IDs, and every observation are checked before export; process IDs, position counts, and full-pass totals remain in the summaries. Quality remains three distinct text scores; speed is the page-weighted arithmetic mean across all HTML in the reported passes, with per-source breakdowns retained for inspection.

### Historical Adapter

The existing historical Go adapters require Go 1.22.5+. They remain available without changing their module graph:

```sh
python prepare.py
python -B -m unittest discover -p 'test_*.py' -v
go test -mod=readonly ./...
go build -mod=readonly -o .cache/extract ./cmd/extract
python benchmark.py run --name legacy-go-trafilatura --version v1.11.2-0.20240925233727-6a4807611f40 --profile core-only --output results/legacy-dev-predictions.json --command .cache/extract -extractor trafilatura
python benchmark.py evaluate --predictions results/legacy-dev-predictions.json --output results/legacy-dev-evaluation.json
```

On Windows, build `.cache/extract.exe` and pass that path to `--command`. When Go is not on `PATH`, pass `--go "C:/Program Files/Go/bin/go.exe"` to preparation. A custom cache location is supported through `--data` on both commands.

The bundled adapter intentionally uses the repository's **existing historical Go dependency versions**, not the current Go-Trafilatura worktree. No dependency upgrade is implied by these examples. Use a separately built adapter and its exact version/revision to evaluate another release or local change. The adapter supports `-extractor trafilatura`, `readability`, or `domdistiller`; Trafilatura additionally supports `-fallback` and `-focus balanced|precision|recall`. Comments are excluded and tables included; DomDistiller pagination is disabled. `benchmark.py` performs one serial quality pass, not a timing benchmark; `compare.py` can use the same adapter for repeated process measurements.

`run` saves predictions; `evaluate` writes four separately named evaluations in one JSON report, including per-page results, WCXB page-type groups, error/empty counts, metadata denominators, source pins, and input/output hashes. Failures must emit empty text and an error: they are scored, not dropped. Missing, extra, or duplicate prediction IDs are rejected.

For native fallbacks, make a separate run with `--profile native-fallbacks`, record actual settings in `--options '{"fallback":true}'`, and pass `-fallback` to the adapter. `--options` documents settings; it does not configure an external adapter. Never combine core-only and fallback-enabled results under one label. Omitted options remain visible as an empty object, and the exact command is retained with predictions.

Use `--wcxb-split test` consistently on `run` and `evaluate` for the cleaned holdout. Add `--upstream-records` consistently to reproduce the original record membership. Neither option changes scoring rules. The three text F1 scores have different units and aggregation and must not be averaged into a purported universal F1.

The default development run contains **2,659 pages**: 983 LegoNews, 181 ScrapingHub, and 1,495 WCXB development pages. A `test` run contains **1,536 pages**: the same LegoNews and ScrapingHub controls, plus 372 WCXB test pages. Only the latter are held out. In particular, an improvement in the combined test-profile metadata score can come entirely from repeated development controls; report the WCXB test fields separately.

## Compare Accuracy, Speed, And Memory

### Any Scraper Set

[compare.py](compare.py) runs any configured set of foreground JSONL adapters using the protocol below. Install its dependency in your chosen Python environment and build adapters before measuring:

```sh
python -m pip install -r requirements-performance.txt
go build -mod=readonly -trimpath -pgo=off -o .cache/extract ./cmd/extract
python compare.py --config compare.example.json --output results/legacy-comparison --runs 6 --memory-runs 6
```

On Windows, build `.cache/extract.exe`; the example config expands `{exe}` to `.exe` on Windows and an empty string elsewhere. The [example configuration](compare.example.json) compares all three bundled **historical** scrapers without changing the root Go dependency graph. Select any subset by repeating `--scraper`:

```sh
python compare.py --config compare.example.json --scraper legacy-readability --scraper legacy-domdistiller --output results/selected-comparison --runs 4 --memory-runs 4
```

Add or remove entries in the config's `scrapers` array to compare other implementations. Each entry declares:

- `name`: a unique filename-safe identifier; `version`: an exact release, revision, or dirty-source fingerprint; `profile`: the extraction mode.
- `command`: an executable and arguments as a JSON array, never a shell command. Python, Node, native binaries, and other runtimes use the same protocol. Adapters must finish their work and wait for their children before exiting; do not launch detached services.
- `cwd`: the working directory, relative to the config directory by default. Executable paths and `artifacts` paths are resolved from this directory; a bare executable name is found on `PATH`.
- `options`: explicit extraction settings for provenance. These do **not** configure the program; matching arguments belong in `command`.
- `env`: explicit runtime controls such as thread counts, GC settings, and time zone. Unspecified variables are inherited. The examples use serial extraction and `GOMAXPROCS=1`; the controller does not add extractor workers.
- `artifacts`: adapter scripts, dependency locks, models, and/or build receipts to hash with the executable. Include everything needed to identify interpreted adapters, not just the Python/Node executable. Use already installed local models; the runner does not install models or prepare an external runtime.

Unselected scraper executables need not be installed. When combining entries from configs in different directories, update each entry's `cwd` so its relative command and artifact paths still identify the intended files. Unsupported metadata remains empty; adding another extractor does not require changing the scorers.

### Old And New Go-Trafilatura

[tools/build_go_trafilatura.py](tools/build_go_trafilatura.py) creates immutable source copies, builds the **same v2 adapter** against each copy's own dependency graph, and generates a comparison config. Point it at the canonical Go-Trafilatura Git checkout, not a source mirror inside another repository:

```sh
python tools/build_go_trafilatura.py --source ../go-trafilatura --output .cache/go-trafilatura-ready
python compare.py --config .cache/go-trafilatura-ready/compare.json --output results/go-old-new --mode speed --timing page --runs 4
```

Replace `../go-trafilatura` with your checkout path. For this workspace the canonical checkout is `C:/github/go-trafilatura`. `--go` and `--git` accept executable paths when those tools are not on `PATH`.

The default old revision is saved pre-alignment baseline `72dce36bfe95502563533cf68a9050370a3d7081`, which already includes the newer dependency graph used by the alignment study. The new revision defaults to `WORKTREE`, including dirty tracked files and nonignored untracked files. To compare the published release instead, pass `--old-ref v2.2.1`; that measures the release's dependency differences as well as source changes. `--new-ref REVISION` can replace the worktree snapshot. Required revisions must already be available in the local checkout; the helper does not fetch or switch branches.

Both builds use Go 1.27.1 by default (`--toolchain` can select another exact installed/downloadable Go version), CGO disabled, the host OS/architecture, no PGO, and readonly modules. The helper does not change either source checkout, rewrite dependency locks, or upgrade the benchmark's historical module. Dependency replacements and symlinks/submodules in the snapshots are rejected. Each receipt records the source commit, worktree patch/status, all copied file hashes, selected modules, effective Go settings, adapter hash, command, and executable hash. Keep the generated source copies with the receipts when publishing evidence; a dirty commit label alone is not reproducible.

Default extraction is balanced, core-only, comments off, tables on, and no target-language restriction. `--fallback`, `--comments`, and `--focus` configure **both** builds identically and are recorded in the generated config. Use a separate output directory for each profile. Both the preparation helper and comparison runner refuse to overwrite an existing output directory; edited source requires a new snapshot/build, not reuse of an older binary.

For a bounded wiring check before a full comparison:

```sh
python compare.py --config .cache/go-trafilatura-ready/compare.json --output results/go-old-new-smoke --mode speed --limit-per-corpus 5 --runs 4 --warmups 1
```

This selects a seeded random subset per corpus, not the first pages, and marks the report as a **smoke/sample run**. It cannot establish a full-corpus accuracy or performance conclusion.

### Measurement Contract

- **Warm per-page speed (default `--timing page`):** start one persistent process per scraper and keep all of them alive through warmup and every timed pass. For each page, send one request to the first scraper, wait for its complete response, then do the same for the other scraper(s), before advancing to the next page. Never run two extraction requests concurrently. Each request is timed from sending/flushing JSONL through receiving the full response. This includes IPC, file reads, parsing, extraction, metadata and rendering, but excludes startup, warmup, validation, scoring and controller bookkeeping. It is not DOM-only extraction time.
- **Passes and order:** `--runs N` is tunable and defaults to **4**. Every pass cycles the entire selected page set in the same order; scraper order is seeded separately for each page and balanced over blocks of `2 * scraper_count` passes. With two versions and `N=4`, each version goes first exactly twice for every page. For three scrapers, use six passes for exact position balance. Both processes are warm; one discarded full-data warmup is required and also supplies the reference quality outputs. `--warmups` can increase that count.
- **Reported mean:** total measured request time in milliseconds divided by the number of timed page observations, normally `N * page_count`. Results include each corpus and the page-weighted mean across all selected pages. For 2,659 pages and `N=4`, each scraper has 10,636 timed observations. This is the arithmetic mean, not the median or an unweighted average of the three corpus means. Individual timings, order and persistent process IDs are saved in a transient `page-timings.jsonl` for audit, then removed by the summary-only release workflow.
- **Batch alternative (`--timing batch`):** retain the original fresh-process, whole-corpus measurement for startup-inclusive workloads. One scraper processes the entire corpus, then the next does; order changes between rounds, not between pages. Batch time includes startup and exit. Its amortized milliseconds/page must not be mixed with the persistent per-page latency above. Batch mode does a separate quality pass before fresh-process warmups and timed rounds.
- **Quality:** retain the three separate text scores and annotated author/title/date scores. In page mode these come from the first warmup, without restarting the processes. Failed pages remain in the denominator and visible in error counts; fast failures are not evidence of successful extraction throughput. The same strict input/protocol checks used by `benchmark.py` apply.
- **Memory:** separate fresh-process runs, sampling the sum of resident memory (RSS) of the scraper and its live descendants every `--sample-ms` milliseconds, default 10. Reported memory is the median of sampled batch peaks, not cumulative allocations, Go heap usage, or exact OS peak RSS. Short peaks may be missed and shared pages may be counted in multiple processes. The Python controller is excluded. Memory sampling never runs during speed passes.
- **Memory counts:** `--memory-runs` is independent of `--runs` and defaults to three runs per scraper per corpus. Use four for balanced positions with two scrapers or six for three. Memory runs start only after the warm speed processes have exited. `--mode speed` does not measure memory.
- **Controls:** `--mode quality|speed|memory|all` selects phases; every mode includes quality validation. `--corpus` and `--scraper` are repeatable. `--cpu N` optionally pins inherited process affinity to one available logical CPU where supported; it is restored afterward. `--timeout` is a deadline per page request/shutdown in page mode, or per process in batch mode. Record matching extractor options and explicit runtime settings when attributing a difference to code.
- **Stability:** every repeat must match that scraper's reference body text and normalized scored metadata. Author ordering alone is ignored. Raw outputs, including unscored fields, are retained. Protocol errors, artifact changes, output instability, timeouts, and detected wall/monotonic clock divergence leave an incomplete report rather than a successful result.
- **Outputs:** `compare.py` creates a new run directory containing `REPORT.md`, `comparison.json`, raw JSONL predictions, stderr files, and page observations in page mode. Session output streams contain repeated IDs across passes; the timing log identifies the corresponding phase, pass and page. The internal report includes mean milliseconds/page, pass totals and ranges, source/input/annotation hashes, options, runtime controls, and per-page quality results. `--publication-date YYYY-MM-DD` also exports separate dated quality/performance JSON with a common comparison hash; incomplete runs do not produce these exports. The release quick start audits these transient files, exports compact summaries with [tools/publish_results.py](tools/publish_results.py), and removes the raw run. Speedup is the first selected scraper's mean divided by each row's mean within the same corpus. It is not an accuracy-adjusted score or a confidence interval.
- **Diagnostics:** per-pass process CPU time and before/after power status are recorded outside request timers. CPU time is diagnostic only: it never replaces request wall time, removes outliers, or changes the reported denominator. Compare only within the same combined run, never ratios or absolute times borrowed from earlier runs.

Keep the machine awake and free of concurrent builds or other heavy work. Record power conditions; battery operation alone is not grounds to reject or trim a run. Page pairing reduces timing drift, but co-resident runtimes, background GC, OS scheduling and shared caches can still affect measurements. Do not infer cold-cache performance. The clock check cannot detect all suspension, throttling, or host contention. Do not pool these measurements with older timings, especially runs invalidated by sleep/standby. A real speed conclusion needs full workloads, repeated samples, comparable quality, and inspection of the observed spread. Go's historical `-benchmem` allocations below measure a different memory quantity and are not comparable to RSS.

## Extractor Protocol

`benchmark.py run ... --command EXE ARGS...` starts one process and sends JSON lines on stdin. Put `--command` last. Each request contains only inputs, never labels or page-type hints:

```json
{"id":"wcxb/dev/0001","url":"https://example.com/article","html_path":"/absolute/cache/html/hash.html"}
```

Return exactly one JSON line per request on stdout; send diagnostics to stderr. For persistent page timing, flush each complete response immediately and continue reading requests without waiting for stdin to close. For Python adapters, use `print(..., flush=True)` or unbuffered output (`python -u`):

```json
{"id":"wcxb/dev/0001","text":"Article text","metadata":{"title":"Article title","authors":["Jane Smith"],"date":"2026-01-02"}}
```

For rejected/failed pages:

```json
{"id":"wcxb/dev/0001","text":"","metadata":{},"error":"extraction rejected"}
```

Use plain article text, not Markdown or serialized HTML. Keep metadata separate; do not insert author/date values into content to improve a score. Preserve source author units: arrays are sets of separately supplied units; a combined byline string remains one unit unless the extractor exposes separate names. Do not guess name boundaries from commas or words such as `and`. The legacy Trafilatura adapter splits its documented semicolon separator; the Readability byline is retained intact. Unsupported metadata is left empty, not synthesized by another library.

External runners can use `python benchmark.py inputs --output results/inputs.json` to obtain label-free paths and exact benchmark provenance. Produce a prediction envelope with `schema_version: 1`, `name`, `version`, `profile`, `options`, the unchanged `benchmark` object from that export, and `predictions: {record_id: {text, metadata, error}}`. The evaluator accepts this same format regardless of implementation language. WCXB IDs include the split because filenames recur across splits.

## Metadata Rules

Metadata is a **fourth evaluation**, not part of text F1. LegoNews supplies 552 nonempty author, 869 title, and 748 date annotations. WCXB supplies additional annotations; each report gives the precise denominator after split selection and deduplication. ScrapingHub has no metadata ground truth and is excluded.

- Score only nonempty, supplied references. Missing, null, and empty annotations are unknown, not confirmed negatives. Author precision is consequently conditional on annotated pages; this benchmark cannot establish the hallucination rate on unlabeled pages.
- Normalize Unicode NFC, case, and whitespace. Keep punctuation, accents, name order within an author unit, and literal date meaning. No fuzzy matching, transliteration, author alias inference, or date guessing.
- Authors: order-independent exact set match and micro precision/recall/F1 over normalized supplied author units. A combined byline is not automatically split into individual people. Report coverage and exact precision as well, so always-empty output cannot earn a good author score.
- Title and date: normalized exact field match. Emit dates in the source reference's calendar-date form, normally `YYYY-MM-DD`; do not shift a date across time zones in the evaluator.
- Report results per source as well as the combined annotated population. These mixed annotations are not an independently audited universal metadata gold standard.

## Scoring And Verification

LegoNews retains exact snippet matching and micro counts. ScrapingHub preserves case-sensitive four-word sequence counts, token-sequence exact accuracy, and its F1 of mean precision and recall. Its upstream precision calculation excludes empty predictions from the precision denominator, while recall still penalizes them; reports expose that denominator. Undefined all-empty/zero-overlap aggregates are reported as zero rather than crashing. WCXB counts repeated words, lowercases them, ignores order, and averages each page's F1. It is not unique-word set overlap.

The tests compare both full-text scorers with the pinned upstream implementations after preparation. Other tests cover metadata annotation coverage, author normalization, empty/rejected outputs, duplicate detection, split-qualified IDs, and the label-free runner protocol. Preparation verifies cached source files and records immutable HTML/annotation hashes; evaluation checks prediction provenance and annotation hashes.

For decisions, compare the same versions on the same prepared inputs, inspect per-page losses as well as averages, and use paired uncertainty estimates when differences are small. No historical leaderboard score is a measurement of today's source. Published values below are retained as historical context only.

## Change Evaluation Methodology

Use this workflow to decide whether an extraction change should be retained. Quality against corpus annotations, fidelity to another implementation, and execution speed are separate questions. A higher F1 does not prove upstream equivalence; exact agreement with upstream does not guarantee better extraction.

1. **Name and freeze the baseline.** Record the source commit, any uncommitted patch, source-file hashes, dependency locks, toolchain, adapter source, and built executable hash. A commit alone does not identify a dirty worktree. Keep the prepared HTML, annotations, parser entry point, and extraction settings identical. Do not label the bundled historical adapter as a current release.
2. **Change one behavior at a time.** Build each variant from the same frozen baseline in an isolated copy, with an exact patch and its own executable identity. Name the direction explicitly, such as "restore old author-selector whitespace normalization." These are independent comparisons, not cumulative changes; their effects need not add. Test a proposed combination separately before claiming its combined result.
3. **Check the targeted behavior.** Run nearby regression tests as well as the corpus. Where useful, verify that deliberately removing a safeguard makes its regression fail. Repeat the unchanged baseline once to detect unstable text or scored metadata before attributing differences to a variant.
4. **Evaluate development inputs serially.** Keep core-only and native-fallback runs separate. Record all relevant settings, including focus, comments, tables, images, links, deduplication, and target language. Use a separate comments-enabled profile for comment rules. Changing an option in the provenance object does not configure the adapter.
5. **Inspect gains and losses.** Retain predictions, errors, per-page scores, and each corpus's own aggregate. Report changed-output counts, page-level wins/losses, metadata denominators, and WCXB page-type groups. Inspect large losses and concentration within a domain or template; many pages from one site are not independent demonstrations of general improvement.
6. **Quantify uncertainty appropriately.** If using paired bootstrap intervals, resample the same page IDs for baseline and variant within each corpus and recompute that corpus's actual aggregate. Record the seed, resample count, confidence level, and clustering policy. Do not substitute mean page F1 for LegoNews or ScrapingHub's aggregate, or treat many exploratory comparisons as one prespecified significance test.
7. **Predeclare the holdout comparison.** Select the candidate, endpoints, and regression guards using development results; save that decision before test extraction. Evaluate the frozen candidate and baseline on the cleaned WCXB test subset without retuning. Separately rerun retained native-fallback behavior when the proposed change can reach that path. Unknown metadata labels cannot confirm a benefit or absence of false authors.
8. **Report a bounded decision.** Separate measured benefits, known regressions, upstream-compatibility choices, and unresolved trade-offs. Preserve input and annotation hashes, exact profiles, raw predictions, patches, and rejected results. Do not fix benchmark labels to fit outputs, add production site-specific exceptions, or infer speed from these quality runs.

`benchmark.py` supplies the input protocol, provenance checks, serial execution, and four scores and remains standard-library-only. `compare.py` adds configurable process comparisons, and the Go preparation helper freezes/builds an old/new v2 pair. Arbitrary variant construction, regression checks, predeclared selection, and statistical analysis remain responsibilities of the experiment using these tools. An experiment may use separate analysis dependencies, which it must record.

### Reference Study

The [September 19 Go-Trafilatura study](RECOMMENDATION_EVALUATION.md) applies this method to a frozen current-v2 worktree: 27 independently changed variants and 34 complete evaluations, including baseline/repeat, comments-enabled checks, native-fallback checks, and one predeclared holdout pair. It is a local study, not a comparison of every released extractor or a new Go-versus-Python parity run.

Its exploratory intervals use 2,000 paired page-level bootstrap resamples, seed `20260919`, and 95% percentile bounds. They are not adjusted for multiple comparisons or clustered by domain. The author-normalization candidate changes 13 held-out WCXB author outputs, all without author annotations: the holdout confirms unchanged scored fields and body text, but cannot establish improved author accuracy on those pages. These limits are part of the result, not exclusions from scoring.

The report links the retained local predictions, build identities, and analysis under ignored `results/` and `.cache/`. Those generated artifacts are not distributed by a normal Git checkout. When publishing another study, provide its evidence artifacts or a reproducible pinned driver explicitly rather than assuming local cache files accompany the documentation.

## Attribution

The original benchmark and LegoNews materials retain their [Apache-2.0 license](LICENSE) and Go-Trafilatura provenance. ScrapingHub's benchmark repository is MIT-licensed. WCXB is attributed to Murrough Foley under CC-BY-4.0; source links and DOI appear above and in every prepared manifest/report. Cached web-page content remains subject to its original publishers' rights; a benchmark repository license is not a blanket relicensing of those pages. This project downloads pinned sources for local evaluation instead of committing a second copy of the external corpora.

## Historical Go Comparison

The following overview and measurements describe the original repository snapshot and dependency versions. They are not new results for the four standard evaluations.

## Extractors Overview

As far as we know, currently there are three content extractors built for Go:

- [Go-DomDistiller][dom-distiller]
- [Go-Readability][readability]
- [Go-Trafilatura][trafilatura]

Since every extractors use its own algorithms, their results are a bit different. In general they give satisfactory results, however we found out that there are some cases where DOM Distiller is better and vice versa. Here is the short summary of pros and cons for each extractor:

Dom Distiller:

- Very fast.
- Good at extracting images from article.
- Able to find next page in sites that separated its article to several partial pages.
- Since the original library was embedded in Chromium browser, its tests are pretty thorough.
- CON: has a huge codebase, mostly because it mimics the original Java code.
- CON: the original library is not maintained anymore and has been archived.

Readability:

- Fast, although not as fast as Dom Distiller.
- Better than DOM Distiller at extracting wiki and documentation pages.
- The original library in Readability.js is still actively used and maintained by Firefox.
- The codebase is pretty small.
- CON: the unit tests are not as thorough as the other extractors.

Trafilatura:

- Has the best accuracy compared to other extractors.
- Better at extracting web page's metadata, including its language and publish date.
- Its unit tests are thorough and focused on removing noise while making sure the real contents are still captured.
- Designed to be used in academic domain e.g. natural language processing.
- Actively maintained with new release almost every month.
- CON: slower than the other extractors, mostly because it also looks for language and publish date.
- CON: doesn't really good at extracting images.

## Benchmark Result

This benchmark uses each extractor to process 983 web pages in single thread. To test the benchmark, run it with following command:

```
go test -bench=. -benchmem -v
```

Here is its benchmark result when tested in my PC (Intel i7-8550U @ 4.000GHz, RAM 16 GB):

|             Extractor             | Time (ms) | Memory (MB) | Mem Allocation (allocs) |
| :-------------------------------: | :-------: | :---------: | :---------------------: |
|            Readability            |   4,212   |    4,412    |       15,261,650        |
|           DomDistiller            |   3,794   |    4,144    |       13,552,246        |
|  DomDistiller+PaginationPrevNext  |   5,263   |    4,598    |       22,744,038        |
| DomDistiller+PaginationPageNumber |   4,156   |    4,222    |       15,669,698        |
|            Trafilatura            |   6,609   |    3,585    |       33,628,972        |
|       Trafilatura+Fallback        |  12,934   |    8,781    |       55,338,023        |
|       Trafilatura+Precision       |  13,644   |    8,763    |       57,549,026        |
|        Trafilatura+Recall         |  10,083   |    5,454    |       43,626,869        |

And here is its performance result:

|             Extractor             | Precision | Recall | Accuracy | F-Score |
| :-------------------------------: | :-------: | :----: | :------: | :-----: |
|            Readability            |   0.870   | 0.881  |  0.875   |  0.875  |
|           DomDistiller            |   0.871   | 0.864  |  0.868   |  0.867  |
|  DomDistiller+PaginationPrevNext  |   0.871   | 0.864  |  0.868   |  0.867  |
| DomDistiller+PaginationPageNumber |   0.871   | 0.864  |  0.868   |  0.867  |
|            Trafilatura            |   0.909   | 0.885  |  0.899   |  0.897  |
|       Trafilatura+Fallback        |   0.911   | 0.901  |  0.907   |  0.906  |
|       Trafilatura+Precision       |   0.923   | 0.875  |  0.901   |  0.899  |
|        Trafilatura+Recall         |   0.897   | 0.910  |  0.903   |  0.903  |

If you are interested, here is its raw output:

<details>
	<summary>Raw output</summary>

    ```
    goos: linux
    goarch: amd64
    pkg: github.com/markusmobius/content-extractor-benchmark
    cpu: Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz
    Benchmark
    Benchmark/Readability
        benchmark_test.go:52: precision: 0.870, recall: 0.881, accuracy: 0.875, f-score: 0.875, duration: 4.213s
    Benchmark/Readability-8         	       1	4212881418 ns/op	4412465904 B/op	15261650 allocs/op
    Benchmark/DomDistiller
        benchmark_test.go:52: precision: 0.871, recall: 0.864, accuracy: 0.868, f-score: 0.867, duration: 3.794s
    Benchmark/DomDistiller-8        	       1	3794298841 ns/op	4144517376 B/op	13552246 allocs/op
    Benchmark/DomDistiller+PaginationPrevNext
        benchmark_test.go:52: precision: 0.871, recall: 0.864, accuracy: 0.868, f-score: 0.867, duration: 5.263s
    Benchmark/DomDistiller+PaginationPrevNext-8         	       1	5263629602 ns/op	4598173040 B/op	22744038 allocs/op
    Benchmark/DomDistiller+PaginationPageNumber
        benchmark_test.go:52: precision: 0.871, recall: 0.864, accuracy: 0.868, f-score: 0.867, duration: 4.156s
    Benchmark/DomDistiller+PaginationPageNumber-8       	       1	4156136296 ns/op	4222801984 B/op	15669698 allocs/op
    Benchmark/Trafilatura
        benchmark_test.go:52: precision: 0.909, recall: 0.885, accuracy: 0.899, f-score: 0.897, duration: 6.609s
    Benchmark/Trafilatura-8                                	       1	6609371951 ns/op	3585812608 B/op	33628972 allocs/op
    Benchmark/Trafilatura+Fallback
        benchmark_test.go:52: precision: 0.911, recall: 0.901, accuracy: 0.907, f-score: 0.906, duration: 12.934s
    Benchmark/Trafilatura+Fallback-8                       	       1	12934427664 ns/op	8781635928 B/op	55338023 allocs/op
    Benchmark/Trafilatura+Precision
        benchmark_test.go:52: precision: 0.923, recall: 0.875, accuracy: 0.901, f-score: 0.899, duration: 13.645s
    Benchmark/Trafilatura+Precision-8                      	       1	13644700764 ns/op	8763154048 B/op	57549026 allocs/op
    Benchmark/Trafilatura+Recall
        benchmark_test.go:52: precision: 0.897, recall: 0.910, accuracy: 0.903, f-score: 0.903, duration: 10.084s
    Benchmark/Trafilatura+Recall-8                         	       1	10083675348 ns/op	5454094880 B/op	43626869 allocs/op
    PASS
    ok  	github.com/markusmobius/content-extractor-benchmark	65.437s
    ```

</details>

## License

Since this benchmark is adapted from `go-trafilatura`, this benchmark is also distributed under the [Apache v2.0](LICENSE).

[dom-distiller]: https://github.com/markusmobius/go-domdistiller/
[readability]: https://github.com/go-shiori/go-readability
[trafilatura]: https://github.com/markusmobius/go-trafilatura/
