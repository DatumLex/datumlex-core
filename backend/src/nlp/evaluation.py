"""Exact-span engineering evaluation; results do not establish legal validation."""


def evaluate_annotations(predicted, expected):
    def identities(items):
        return {(label, tuple((s["start"], s["end"], s["text"]) for s in item["segments"]))
                for item in items for label in item["labels"]}

    predictions, gold = identities(predicted), identities(expected)
    correct = len(predictions & gold)
    precision = correct / len(predictions) if predictions else None
    recall = correct / len(gold) if gold else None
    f1 = 2 * correct / (len(predictions) + len(gold)) if predictions or gold else None
    return {"true_positive": correct, "false_positive": len(predictions - gold), "false_negative": len(gold - predictions),
            "precision": precision, "recall": recall, "f1": f1, "matching": "exact_label_and_source_span",
            "legal_validation": "not_established"}
