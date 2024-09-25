package benchmark

import (
	"testing"

	distiller "github.com/markusmobius/go-domdistiller"
	gt "github.com/markusmobius/go-trafilatura"
)

func Benchmark(b *testing.B) {
	names := []string{
		"Readability",
		"DomDistiller",
		"DomDistiller+PaginationPrevNext",
		"DomDistiller+PaginationPageNumber",
		"Trafilatura",
		"Trafilatura+Fallback",
		"Trafilatura+Precision",
		"Trafilatura+Recall",
	}

	infoLogger := b.Logf
	errrorLogger := b.Errorf

	runners := []ExtractorRunner{
		initReadability(infoLogger),
		initDomDistiller(infoLogger, -1),
		initDomDistiller(infoLogger, int(distiller.PrevNext)),
		initDomDistiller(infoLogger, int(distiller.PageNumber)),
		initTrafilatura(infoLogger, false, gt.Balanced),
		initTrafilatura(infoLogger, true, gt.Balanced),
		initTrafilatura(infoLogger, true, gt.FavorPrecision),
		initTrafilatura(infoLogger, true, gt.FavorRecall),
	}

	extractorParameters := initExtractorParameter(errrorLogger)

	for i, runner := range runners {
		b.Run(names[i], func(b *testing.B) {
			var perf ExtractionPerformance
			for i := 0; i < b.N; i++ {
				perf, _ = runner(extractorParameters)
			}

			infoLogger("%s", perf.String())
		})
	}
}
