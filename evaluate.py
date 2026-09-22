"""Independent quality metrics for the four standard extraction benchmarks."""

from collections import Counter
import re
import statistics
import unicodedata


def ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def harmonic(precision, recall):
    return ratio(2 * precision * recall, precision + recall)


def snippet_counts(text, wanted, unwanted):
    return {
        "true_positives": sum(snippet in text for snippet in wanted),
        "false_negatives": sum(snippet not in text for snippet in wanted),
        "false_positives": sum(snippet in text for snippet in unwanted),
        "true_negatives": sum(snippet not in text for snippet in unwanted),
    }


def legonews_metrics(counts):
    totals = {
        field: sum(page[field] for page in counts)
        for field in (
            "true_positives", "false_negatives", "false_positives", "true_negatives"
        )
    }
    true_positive = totals["true_positives"]
    false_positive = totals["false_positives"]
    false_negative = totals["false_negatives"]
    return {
        **totals,
        "precision": ratio(true_positive, true_positive + false_positive),
        "recall": ratio(true_positive, true_positive + false_negative),
        "f1": ratio(2 * true_positive, 2 * true_positive + false_positive + false_negative),
        "accuracy": ratio(true_positive + totals["true_negatives"], sum(totals.values())),
    }


def tokens(text, lowercase=False):
    return re.findall(r"\w+", text.lower() if lowercase else text)


def shingles(text):
    words = tokens(text)
    return Counter(
        tuple(words[offset:offset + 4])
        for offset in range(max(1, len(words) - 3))
        if words[offset:offset + 4]
    )


def scrapinghub_page(predicted, reference):
    prediction = shingles(predicted)
    expected = shingles(reference)
    overlap = sum((prediction & expected).values())
    return {
        "matched": overlap,
        "predicted": sum(prediction.values()),
        "expected": sum(expected.values()),
        "accuracy": float(tokens(predicted) == tokens(reference)),
    }


def scrapinghub_metrics(pages):
    precision_values = [
        page["matched"] / page["predicted"] for page in pages if page["predicted"]
    ]
    recall_values = [
        page["matched"] / page["expected"] for page in pages if page["expected"]
    ]
    precision = statistics.mean(precision_values) if precision_values else 0.0
    recall = statistics.mean(recall_values) if recall_values else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": harmonic(precision, recall),
        "accuracy": statistics.mean(page["accuracy"] for page in pages) if pages else 0.0,
        "precision_pages": len(precision_values),
        "recall_pages": len(recall_values),
    }


def wcxb_page(predicted, reference):
    prediction = Counter(tokens(predicted, lowercase=True))
    expected = Counter(tokens(reference, lowercase=True))
    if not expected:
        score = float(not prediction)
        return {"precision": score, "recall": score, "f1": score}
    overlap = sum((prediction & expected).values())
    precision = ratio(overlap, sum(prediction.values()))
    recall = ratio(overlap, sum(expected.values()))
    return {"precision": precision, "recall": recall, "f1": harmonic(precision, recall)}


def wcxb_metrics(pages):
    return {
        field: statistics.mean(page[field] for page in pages) if pages else 0.0
        for field in ("precision", "recall", "f1")
    }


def normalized(value):
    if not isinstance(value, str):
        raise ValueError("Metadata values must be strings, null, or author string arrays")
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def author_units(value):
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("Authors must be a string, null, or an array of strings")
    return {normalized(author) for author in value if normalized(author)}


def metadata_metrics(pages):
    fields = {}
    for field in ("title", "authors", "date"):
        annotated = correct = populated = true_positive = false_positive = false_negative = 0
        for reference, prediction in pages:
            if field == "authors":
                expected = author_units(reference.get(field))
                actual = author_units(prediction.get(field))
            else:
                expected = normalized(reference.get(field) or "")
                actual = normalized(prediction.get(field) or "")
            if not expected:
                continue
            annotated += 1
            correct += actual == expected
            populated += bool(actual)
            if field == "authors":
                true_positive += len(expected & actual)
                false_positive += len(actual - expected)
                false_negative += len(expected - actual)
        result = {
            "annotated": annotated,
            "unannotated": len(pages) - annotated,
            "correct": correct,
            "predicted_nonempty": populated,
            "exact_match": ratio(correct, annotated) if annotated else None,
            "coverage": ratio(populated, annotated) if annotated else None,
            "exact_precision": ratio(correct, populated) if annotated else None,
        }
        if field == "authors":
            result.update({
                "true_positives": true_positive,
                "false_positives": false_positive,
                "false_negatives": false_negative,
                "precision": ratio(true_positive, true_positive + false_positive) if annotated else None,
                "recall": ratio(true_positive, true_positive + false_negative) if annotated else None,
                "f1": ratio(2 * true_positive, 2 * true_positive + false_positive + false_negative) if annotated else None,
            })
        fields[field] = result
    return fields