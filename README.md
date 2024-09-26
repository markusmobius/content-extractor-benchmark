# Content Extractor Benchmark

This repository becnhmarks various Go' content extractors. The benchmark code and test files are adapted from comparison script in `go-trafilatura`.

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
