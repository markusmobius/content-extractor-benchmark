package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"strconv"
)

func literalValue(expression ast.Expr) (any, error) {
	switch value := expression.(type) {
	case *ast.BasicLit:
		if value.Kind != token.STRING {
			return nil, fmt.Errorf("expected string, got %s", value.Kind)
		}
		return strconv.Unquote(value.Value)
	case *ast.CompositeLit:
		items := make([]string, 0, len(value.Elts))
		for _, element := range value.Elts {
			parsed, err := literalValue(element)
			if err != nil {
				return nil, err
			}
			text, valid := parsed.(string)
			if !valid {
				return nil, fmt.Errorf("expected a string array")
			}
			items = append(items, text)
		}
		return items, nil
	default:
		return nil, fmt.Errorf("unsupported fixture expression %T", expression)
	}
}

func export(path string) error {
	source, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
	if err != nil {
		return err
	}
	fields := map[string]string{
		"File": "file", "URL": "url", "With": "with", "Without": "without",
		"Title": "title", "Authors": "authors", "Date": "date",
	}
	for _, declaration := range source.Decls {
		general, valid := declaration.(*ast.GenDecl)
		if !valid {
			continue
		}
		for _, specification := range general.Specs {
			values, valid := specification.(*ast.ValueSpec)
			if !valid || len(values.Names) != 1 || values.Names[0].Name != "comparisonData" {
				continue
			}
			if len(values.Values) != 1 {
				return fmt.Errorf("comparisonData must have one initializer")
			}
			entries, valid := values.Values[0].(*ast.CompositeLit)
			if !valid {
				return fmt.Errorf("comparisonData must be a literal")
			}
			output := make([]map[string]any, 0, len(entries.Elts))
			for _, element := range entries.Elts {
				entry, valid := element.(*ast.CompositeLit)
				if !valid {
					return fmt.Errorf("expected a literal fixture entry")
				}
				record := make(map[string]any)
				for _, item := range entry.Elts {
					pair, valid := item.(*ast.KeyValueExpr)
					if !valid {
						return fmt.Errorf("expected a named fixture field")
					}
					key, valid := pair.Key.(*ast.Ident)
					if !valid {
						return fmt.Errorf("expected a fixture field identifier")
					}
					name, needed := fields[key.Name]
					if !needed {
						continue
					}
					value, err := literalValue(pair.Value)
					if err != nil {
						return fmt.Errorf("%s: %w", key.Name, err)
					}
					record[name] = value
				}
				output = append(output, record)
			}
			return json.NewEncoder(os.Stdout).Encode(output)
		}
	}
	return fmt.Errorf("comparisonData not found")
}

func main() {
	path := flag.String("data", "data.go", "Go comparison fixture source")
	flag.Parse()
	if err := export(*path); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
