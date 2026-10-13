import asyncio

from casa_agent.agent import _rule_based_params
from casa_agent.models import Listing, Operation, SearchParams
from casa_agent.pipeline import dedup, enrich, hard_filter, run_search, score
from casa_agent.sources import get_sources


def _l(**kw) -> Listing:
    base = dict(id="a:1", source="a", url="http://x", operation=Operation.RENT, price=1000,
                size_m2=60, bedrooms=2, bathrooms=1, district="Centro", neighborhood="Sol",
                address="Calle Mayor 1", lat=40.41, lon=-3.70)
    base.update(kw)
    return Listing(**base)


def test_dedup_merges_same_property_across_sources():
    a = _l(id="a:1", source="a", price=1000)
    b = _l(id="b:1", source="b", price=1030, title="other title")
    c = _l(id="a:2", source="a", price=1000, bedrooms=3)  # different property
    out = dedup([a, b, c])
    assert len(out) == 2
    merged = next(x for x in out if x.bedrooms == 2)
    assert merged.price == 1000  # cheapest copy kept
    assert merged.also_on == ["b"]


def test_dedup_respects_price_gap():
    a = _l(id="a:1", source="a", price=1000)
    b = _l(id="b:1", source="b", price=1300)  # 30% apart → not the same
    assert len(dedup([a, b])) == 2


def test_hard_filter():
    ls = [_l(price=900), _l(id="a:2", price=1500), _l(id="a:3", price=900, bedrooms=1)]
    out = hard_filter(ls, SearchParams(max_price=1000, min_bedrooms=2))
    assert [x.id for x in out] == ["a:1"]


def test_enrich_computes_zone_comparison():
    universe = [_l(id=f"a:{i}", price=1000 + i * 10) for i in range(5)]
    out = enrich(universe[:1], universe)
    assert out[0].price_per_m2 == round(1000 / 60, 2)
    assert out[0].price_vs_zone_pct is not None and out[0].price_vs_zone_pct < 0


def test_score_penalises_overcrowding():
    p = SearchParams(max_price=1500, household_size=5)
    s = score(enrich([_l()], [_l()])[0], p)
    assert any("bedroom" in c for c in s.cons)
    assert 0 <= s.score <= 100


def test_demo_end_to_end():
    p = SearchParams(max_price=1800, min_bedrooms=2, household_size=3)
    r = asyncio.run(run_search(p, get_sources(["demo"])))
    assert r.after_dedup < r.total_found  # demo has cross-portal duplicates
    assert r.options and r.options[0].score >= r.options[-1].score


def test_rule_based_parser():
    p = _rule_based_params("Family of 4 buying in Retiro, budget 650k, 3 bedrooms, parking", None)
    assert p.operation == Operation.BUY and p.max_price == 650000 and p.min_bedrooms == 3
    assert p.household_size == 4 and p.districts == ["Retiro"] and p.needs_parking
    p2 = _rule_based_params("cheaper, drop the parking", p)
    assert p2.max_price < p.max_price and not p2.needs_parking
