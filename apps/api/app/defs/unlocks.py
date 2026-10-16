"""The chain rule behind an approval's `config.also_unlocks`.

A grant lasts for the rest of the run, so the extra writes one approval unlocks must be reachable only through
that approval's granted outcome: every path into one comes from the granted target or from another node the
same approval unlocks, no other outcome of the approval (denied, timeout) can reach one, and none sits on a
loop. The definition validator and the Studio builder share this check; each adds its own rules on the kind of
node and tool."""

from collections.abc import Mapping

GRANTED = "granted"


def _reach(routes: Mapping[str, Mapping[str, str]], starts: list[str]) -> set[str]:
    """Every node reachable from `starts` (the starts included)."""
    seen: set[str] = set()
    todo = list(starts)
    while todo:
        node = todo.pop()
        if node in seen:
            continue
        seen.add(node)
        todo += list((routes.get(node) or {}).values())
    return seen


def chain_problems(
    routes: Mapping[str, Mapping[str, str]], approval: str, unlocked: list[str]
) -> dict[str, str]:
    """What is wrong with each node `approval` also unlocks, by node id, in the order they were named (a node
    with no problem is absent). `routes` maps every node id to its outcome -> next node map. Each reason is a
    phrase to follow "<node> ...". Nodes the caller already found missing are skipped.

    The granted target G is part of the chain: the grant only covers the chain if nothing but the approval's
    granted outcome leads into G and G is not on a loop, so a non-empty chain requires that of G too."""
    mine = routes.get(approval) or {}
    granted = mine.get(GRANTED)
    chain = [u for u in dict.fromkeys(unlocked) if u in routes]
    if not chain:
        return {}
    allowed = ({granted} if granted else set()) | set(chain)
    after_other = _reach(routes, [t for label, t in mine.items() if label != GRANTED])
    leaks = _target_leaks(routes, approval, granted)
    out: dict[str, str] = {}
    for node in chain:
        sources = [(s, label) for s, outs in routes.items() for label, t in outs.items() if t == node]
        stray = sorted(s for s, _ in sources if s != approval and s not in allowed)
        if not sources:
            out[node] = "has nothing leading to it"
        elif node in _reach(routes, list((routes.get(node) or {}).values())):
            out[node] = "sits on a loop, so the grant would outlive the approval"
        elif stray:
            out[node] = (
                f"can be reached from {', '.join(stray)}, which this approval's grant does not cover; "
                "only its granted outcome and the steps it also unlocks may lead there"
            )
        elif node in after_other:
            out[node] = "can be reached after this approval is denied or times out"
        elif leaks:
            out[node] = f"can be reached without this approval through {granted}: {leaks}"
    return out


def _target_leaks(routes: Mapping[str, Mapping[str, str]], approval: str, granted: str | None) -> str:
    """Why the granted target is not reachable only through the approval's granted outcome ("" when it is)."""
    if not granted or granted not in routes:
        return ""
    sources = sorted(
        {s for s, outs in routes.items() for label, t in outs.items() if t == granted} - {approval}
    )
    other = [label for label, t in (routes.get(approval) or {}).items() if t == granted and label != GRANTED]
    if sources or other:
        return f"{', '.join(sources or [approval])} also lead there"
    if granted in _reach(routes, list((routes.get(granted) or {}).values())):
        return "it sits on a loop"
    return ""
