from django.db.models import Count, Q

from src.db.models import DecisionAssessment, DimSubject
from src.services.precedent_usage import summarize as precedent_usage
from src.services.report_nlp import report_nlp


def report_context(query, scope, actor=None):
    annual = list(
        query.order_by()
        .values("time__year")
        .annotate(
            documents=Count("pk"),
            granted=Count("pk", filter=Q(result__name="granted")),
            denied=Count("pk", filter=Q(result__name="denied")),
        )
        .order_by("time__year")
    )
    assessments = (
        DecisionAssessment.objects.filter(
            local_decision__court="TJDFT",
            decision_date__range=[scope["start"], scope["end"]],
            review_state=DecisionAssessment.REVIEW_APPROVED,
            reference__approved=True,
            reference__reference_type="precedent",
            reference__source_institution="STJ",
        )
        if "TJDFT" in scope["court"].split(",")
        else DecisionAssessment.objects.none()
    )
    if scope["subject"]:
        assessments = assessments.filter(local_decision__subjects__code=scope["subject"])
    counts = {
        row["relation"]: row["count"]
        for row in assessments.order_by().values("relation").annotate(count=Count("pk", distinct=True))
    }
    subject = (
        DimSubject.objects.filter(code=scope["subject"]).values_list("name", flat=True).first()
        if scope["subject"]
        else None
    )
    return {"annual": annual, "assessments": counts, "subject_name": subject, "nlp": report_nlp(scope, actor), "precedent_usage": precedent_usage(scope)}
