def case_summaries(query):
    classified_results = query.filter(result__name__in=["granted", "denied", "partial"])
    selected = classified_results if classified_results.exists() else query
    return list(
        selected.select_related("process_dimension", "organization", "process_class", "time", "result")
        .order_by("-time__date", "-pk")
        .values(
            "process_dimension__number_process",
            "court",
            "process_class__name",
            "organization__name",
            "time__date",
            "result__name",
        )[:5]
    )
