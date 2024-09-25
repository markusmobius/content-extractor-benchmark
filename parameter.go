package benchmark

import (
	"fmt"
	nurl "net/url"
	"os"
	fp "path/filepath"

	"github.com/go-shiori/dom"
	"golang.org/x/net/html"
)

const (
	fileDir = "files"
)

type ExtractorParameter struct {
	ComparisonEntry
	URL      *nurl.URL
	Document *html.Node
}

func initExtractorParameter(logger FnLogger) []ExtractorParameter {
	var params []ExtractorParameter

	for _, entry := range comparisonData {
		// Make sure URL is valid
		url, err := nurl.ParseRequestURI(entry.URL)
		if err != nil {
			logger("failed to parse %s: %v", entry.URL, err)
			continue
		}

		// Open file
		f, err := openEntryFile(entry.File)
		if err != nil {
			logger("%v", err)
			continue
		}

		// Create document
		doc, err := dom.Parse(f)
		if err != nil {
			logger("failed to parse %s: %v", entry.File, err)
			continue
		}

		// Save parameters
		params = append(params, ExtractorParameter{
			ComparisonEntry: entry,

			URL:      url,
			Document: doc,
		})
	}

	return params
}

func openEntryFile(name string) (*os.File, error) {
	f, err := os.Open(fp.Join(fileDir, name))
	if err == nil {
		return f, nil
	}
	return nil, fmt.Errorf("failed to open %s", name)
}
