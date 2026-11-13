from decimal import Decimal, InvalidOperation


def check_question(rule, answer):
    if rule.get("accept_nonempty"):
        return isinstance(answer, str) and bool(answer.strip())
    if "correct_choice_ids" in rule:
        if rule.get("selection")=="one":return isinstance(answer,str) and answer in rule["correct_choice_ids"]
        values = answer if isinstance(answer,list) else [answer]
        return all(isinstance(x,str) for x in values) and len(values)==len(set(values)) and set(values)==set(rule["correct_choice_ids"])
    if not isinstance(answer,str):return False
    if "tolerance" in rule:
        try:
            actual=Decimal(answer.strip())
            expected=Decimal(rule["answers"][0])
            tolerance=str(rule.get("tolerance") or "0")
            delta=abs(expected)*Decimal(tolerance[:-1])/100 if tolerance.endswith("%") else Decimal(tolerance)
            return actual.is_finite() and expected.is_finite() and abs(actual-expected)<=delta
        except (InvalidOperation,ValueError):return False
    normalize = (lambda x:x.strip()) if rule.get("case_sensitive",True) else (lambda x:x.strip().casefold())
    return any(normalize(answer)==normalize(str(expected)) for expected in rule.get("answers",[]))


def assess(grading, responses, locked=frozenset()):
    """`locked` is the set of question ids currently in an anti-brute-force cooldown.

    A locked question is neither re-evaluated against the freshly submitted answer nor
    given fresh feedback: it simply stays marked incorrect until its cooldown expires.
    """
    rules=grading.get("questions",{})
    checks={qid:(False if qid in locked else check_question(rule,responses.get(qid))) for qid,rule in rules.items()}
    fraction=Decimal(sum(checks.values()))/len(checks) if checks else Decimal(0)
    feedback = {}
    for qid, rule in rules.items():
        if qid in locked: continue
        answer = responses.get(qid)
        selected = answer if isinstance(answer,list) else [answer]
        entries = []
        if "choice_feedback_rules" in rule:
            for cid, hints in rule["choice_feedback_rules"].items():
                for hint in hints:
                    if hint["selected"] == (cid in selected) and hint["content"]:
                        entries.append({"choice_id":cid,"content":hint["content"]})
        else:
            for cid, content in rule.get("choice_feedback", {}).items():
                if cid in selected and content: entries.append({"choice_id":cid,"content":content})
        if entries: feedback[qid] = entries
    return {"checks":checks,"feedback":feedback,"fraction":fraction,"passed":bool(checks) and all(checks.values())}

def display_points(value):
    return format(Decimal(value).quantize(Decimal("0.000001")).normalize(), "f")
