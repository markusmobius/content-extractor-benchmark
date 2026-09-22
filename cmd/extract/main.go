package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"

	"github.com/go-shiori/dom"
	"github.com/go-shiori/go-readability"
	distiller "github.com/markusmobius/go-domdistiller"
	trafilatura "github.com/markusmobius/go-trafilatura"
)

type request struct {
	ID       string `json:"id"`
	URL      string `json:"url"`
	HTMLPath string `json:"html_path"`
}

type metadata struct {
	Title   string   `json:"title,omitempty"`
	Authors []string `json:"authors,omitempty"`
	Date    string   `json:"date,omitempty"`
}

type prediction struct {
	ID       string   `json:"id"`
	Text     string   `json:"text"`
	Metadata metadata `json:"metadata"`
	Error    string   `json:"error,omitempty"`
}

func authors(value string, semicolons bool) []string {
	values := []string{value}
	if semicolons {
		values = strings.Split(value, ";")
	}
	var output []string
	for _, item := range values {
		if item = strings.TrimSpace(item); item != "" {
			output = append(output, item)
		}
	}
	return output
}

func extract(input request, engine string, options trafilatura.Options) prediction {
	output := prediction{ID: input.ID}
	file, err := os.Open(input.HTMLPath)
	if err != nil {
		output.Error = err.Error()
		return output
	}
	defer file.Close()
	document, err := dom.Parse(file)
	if err != nil {
		output.Error = err.Error()
		return output
	}
	originalURL, parseErr := url.ParseRequestURI(input.URL)
	if parseErr != nil {
		originalURL = nil
	}
	switch engine {
	case "trafilatura":
		options.OriginalURL = originalURL
		result, extractErr := trafilatura.ExtractDocument(document, options)
		err = extractErr
		if err == nil {
			output.Text = result.ContentText
			output.Metadata.Title = result.Metadata.Title
			output.Metadata.Authors = authors(result.Metadata.Author, true)
			if !result.Metadata.Date.IsZero() {
				output.Metadata.Date = result.Metadata.Date.Format("2006-01-02")
			}
		}
	case "readability":
		result, extractErr := readability.FromDocument(document, originalURL)
		err = extractErr
		if err == nil {
			output.Text = result.TextContent
			output.Metadata.Title = result.Title
			output.Metadata.Authors = authors(result.Byline, false)
		}
	case "domdistiller":
		result, extractErr := distiller.Apply(document, &distiller.Options{OriginalURL: originalURL, SkipPagination: true})
		err = extractErr
		if err == nil {
			output.Text = result.Text
			output.Metadata.Title = result.Title
		}
	}
	if err != nil {
		output.Error = err.Error()
	}
	return output
}

func run() error {
	engine := flag.String("extractor", "trafilatura", "trafilatura, readability, or domdistiller; versions remain pinned by go.mod")
	fallback := flag.Bool("fallback", false, "Enable the existing Go Trafilatura fallback")
	focus := flag.String("focus", "balanced", "balanced, precision, or recall")
	flag.Parse()
	if *engine != "trafilatura" && *engine != "readability" && *engine != "domdistiller" {
		return fmt.Errorf("unknown extractor: %s", *engine)
	}
	options := trafilatura.Options{EnableFallback: *fallback, ExcludeComments: true, ExcludeTables: false}
	switch *focus {
	case "balanced":
		options.Focus = trafilatura.Balanced
	case "precision":
		options.Focus = trafilatura.FavorPrecision
	case "recall":
		options.Focus = trafilatura.FavorRecall
	default:
		return fmt.Errorf("unknown focus: %s", *focus)
	}
	if *engine != "trafilatura" && (*fallback || *focus != "balanced") {
		return fmt.Errorf("fallback and focus apply only to trafilatura")
	}
	decoder := json.NewDecoder(os.Stdin)
	encoder := json.NewEncoder(os.Stdout)
	for {
		var input request
		if err := decoder.Decode(&input); err == io.EOF {
			return nil
		} else if err != nil {
			return err
		}
		if input.ID == "" || input.HTMLPath == "" {
			return fmt.Errorf("each input requires id and html_path")
		}
		if err := encoder.Encode(extract(input, *engine, options)); err != nil {
			return err
		}
	}
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
