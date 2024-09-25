package benchmark

import (
	"fmt"
	"strings"

	"github.com/go-shiori/go-readability"
	distiller "github.com/markusmobius/go-domdistiller"
	gt "github.com/markusmobius/go-trafilatura"
)

type FnLogger func(format string, args ...any)

type ExtractorRunner func([]ExtractorParameter) (ExtractionPerformance, []error)

type EvaluationResult struct {
	TruePositives  int
	FalseNegatives int
	FalsePositives int
	TrueNegatives  int
}

type ExtractionPerformance struct {
	Precision float64
	Recall    float64
	Accuracy  float64
	FScore    float64
}

func (ep ExtractionPerformance) String() string {
	return fmt.Sprintf(""+
		"precision: %.3f, "+
		"recall: %.3f, "+
		"accuracy: %.3f, "+
		"f-score: %.3f",
		ep.Precision,
		ep.Recall,
		ep.Accuracy,
		ep.FScore,
	)
}

func evaluateResult(ev EvaluationResult, result string, entry ComparisonEntry, logger FnLogger) EvaluationResult {
	// Report problematic entry
	if nWith := len(entry.With); nWith == 0 || nWith > 6 {
		logger("entry %s has %d with", entry.File, nWith)
	}

	if nWithout := len(entry.Without); nWithout == 0 || nWithout > 6 {
		logger("entry %s has %d without", entry.File, nWithout)
	}

	// If result empty, return early
	if result == "" {
		ev.FalseNegatives += len(entry.With)
		ev.TrueNegatives += len(entry.Without)
		return ev
	}

	// Check expected output
	for _, str := range entry.With {
		if strings.Contains(result, str) {
			ev.TruePositives++
		} else {
			ev.FalseNegatives++
		}
	}

	// Check unwanted output
	for _, str := range entry.Without {
		if strings.Contains(result, str) {
			ev.FalsePositives++
		} else {
			ev.TrueNegatives++
		}
	}

	return ev
}

func calculatePerformance(ev EvaluationResult) ExtractionPerformance {
	// Calculate performance
	tp := float64(ev.TruePositives)
	fn := float64(ev.FalseNegatives)
	fp := float64(ev.FalsePositives)
	tn := float64(ev.TrueNegatives)
	precision := tp / (tp + fp)
	recall := tp / (tp + fn)
	accuracy := (tp + tn) / (tp + tn + fp + fn)
	fScore := (2 * tp) / (2*tp + fp + fn)

	// Print data
	return ExtractionPerformance{
		Precision: precision,
		Recall:    recall,
		Accuracy:  accuracy,
		FScore:    fScore,
	}
}

func initReadability(logger FnLogger) ExtractorRunner {
	return func(params []ExtractorParameter) (ExtractionPerformance, []error) {
		title := "Readability"

		var errors []error
		var evaluation EvaluationResult
		for _, param := range params {
			article, err := readability.FromDocument(param.Document, param.URL)
			if err != nil {
				err = fmt.Errorf("%s error for %q: %v", title, param.URL, err)
				errors = append(errors, err)
			}
			evaluation = evaluateResult(evaluation, article.TextContent, param.ComparisonEntry, logger)
		}

		perf := calculatePerformance(evaluation)
		return perf, errors
	}
}

func initDomDistiller(logger FnLogger, paginationAlgo int) ExtractorRunner {
	return func(params []ExtractorParameter) (ExtractionPerformance, []error) {
		title := "Dom Distiller"

		var errors []error
		var evaluation EvaluationResult
		for _, param := range params {
			var textResult string
			res, err := distiller.Apply(param.Document, &distiller.Options{
				OriginalURL:    param.URL,
				SkipPagination: paginationAlgo < 0,
				PaginationAlgo: distiller.PaginationAlgo(paginationAlgo),
			})

			if err != nil {
				errors = append(errors, fmt.Errorf("%s error for %q: %v", title, param.URL, err))
			} else {
				textResult = res.Text
			}

			evaluation = evaluateResult(evaluation, textResult, param.ComparisonEntry, logger)
		}

		perf := calculatePerformance(evaluation)
		return perf, errors
	}
}

func initTrafilatura(logger FnLogger, useFallback bool, focus gt.ExtractionFocus) ExtractorRunner {
	return func(params []ExtractorParameter) (ExtractionPerformance, []error) {
		// Prepare Trafilatura options
		opts := gt.Options{
			EnableFallback:  useFallback,
			ExcludeComments: true,
			ExcludeTables:   false,
			Focus:           focus,
		}

		// Initiate extraction result
		var errors []error
		var evaluation EvaluationResult

		// Process each parameter
		for _, param := range params {
			var textResult string
			opts.OriginalURL = param.URL
			result, err := gt.ExtractDocument(param.Document, opts)

			if err != nil {
				errors = append(errors, fmt.Errorf("error for %q: %v", param.URL, err))
			} else {
				textResult = result.ContentText
			}

			evaluation = evaluateResult(evaluation, textResult, param.ComparisonEntry, logger)
		}

		// Return the performance
		perf := calculatePerformance(evaluation)
		return perf, errors
	}
}
