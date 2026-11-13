# Dashboard filters and transferred databases

The corpus exposes the ten initial lexical Civil Liability topics. These are
separate from official numeric CNJ subjects used by the DataJud overview. Topic
counts can overlap and do not constitute legal approval. Empty CNJ names are
shown using their actual code and an explicit missing-name label.

Court selection displays only the courts authorized for the signed-in user.
Selecting all ten courts requires authorization for all ten; frontend options
do not grant permissions. The heading reports the number actually selected.

The corpus topic persists when moving to the thesis tab. The thesis list and
textual precedent-use indicator receive that topic; the list's search and page
reset when its research context changes. CNJ-subject filtering of source theses
requires an explicit reference subject or a reviewed/local assessment carrying
that subject, rather than returning the entire reference library.

The source-thesis period uses reference publication dates. References without a
publication date remain visible with an explicit coverage warning. They are not
assigned an inferred judgment date. Local adherence assessments continue to use
their decision date, and identifier candidates retain their separate date limits.

If no ementa is eligible, the precedent-use card displays an unavailable state
rather than suggesting a 0% application rate. When CNJ-subject confirmation is
missing, the user can explicitly remove that subject filter. A lexical theme is
not promoted to a confirmed CNJ classification.

Local history supports queries since 2016. Code updates do not add historical
data to another installation. A colleague must restore the intended backup into
a separate database, configure the backend connection, and refresh their login
after access changes. A downloaded ZIP alone does not change the running database.

Regression coverage: `test_dashboard_filter_options.py`,
`test_thesis_filter_scope.py`, and `frontend/tests/dashboard-filters.mjs`.
No migrations or data rewrite are required for this correction.
