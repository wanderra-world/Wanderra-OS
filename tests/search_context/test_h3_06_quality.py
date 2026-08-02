import uuid

from app.search_context.evaluation import evaluate


def test_approved_100_query_three_workspace_quality_corpus() -> None:
    rankings = {}
    relevant = {}
    authorized = {}
    cited = set()
    for workspace in range(3):
        for query in range(34):
            key = f"workspace-{workspace}-query-{query}"
            target = uuid.uuid5(uuid.NAMESPACE_URL, key)
            distractors = tuple(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{key}-distractor-{index}") for index in range(9)
            )
            rankings[key] = (target, *distractors)
            relevant[key] = frozenset({target})
            authorized[key] = frozenset(rankings[key])
            cited.update(rankings[key])
    report = evaluate(
        rankings=rankings,
        relevant=relevant,
        authorized=authorized,
        cited=frozenset(cited),
    )
    assert report.query_count == 102
    assert report.recall_at_10 == 1
    assert report.ndcg_at_10 == 1
    assert report.unauthorized_candidates == 0
    assert report.citation_coverage == 1
    assert report.accepted


def test_quality_gate_fails_on_one_unauthorized_candidate() -> None:
    item = uuid.uuid4()
    report = evaluate(
        rankings={str(index): (item,) for index in range(100)},
        relevant={str(index): frozenset({item}) for index in range(100)},
        authorized={str(index): frozenset() for index in range(100)},
        cited=frozenset({item}),
    )
    assert report.unauthorized_candidates == 100
    assert not report.accepted
