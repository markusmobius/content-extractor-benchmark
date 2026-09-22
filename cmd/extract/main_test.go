package main

import (
	"reflect"
	"testing"

	trafilatura "github.com/markusmobius/go-trafilatura"
)

func TestAuthors(t *testing.T) {
	for _, test := range []struct {
		value      string
		semicolons bool
		expected   []string
	}{
		{"", true, nil},
		{" Alice; Bob ", true, []string{"Alice", "Bob"}},
		{"Smith, Jane", true, []string{"Smith, Jane"}},
		{"Alice and Bob", true, []string{"Alice and Bob"}},
		{"Alice; Bob", false, []string{"Alice; Bob"}},
	} {
		if actual := authors(test.value, test.semicolons); !reflect.DeepEqual(actual, test.expected) {
			t.Errorf("authors(%q, %v) = %#v, want %#v", test.value, test.semicolons, actual, test.expected)
		}
	}
}

func TestMissingInputIsAnExplicitEmptyPrediction(t *testing.T) {
	output := extract(request{ID: "legonews/missing", HTMLPath: t.TempDir() + "/missing.html"}, "trafilatura", trafilatura.Options{})
	if output.ID != "legonews/missing" || output.Text != "" || output.Error == "" {
		t.Fatalf("unexpected failed prediction: %#v", output)
	}
}
