---
name: karpathy-examples
description: Concrete code anti-pattern reference — over-abstraction for single-use code, speculative options/flexibility not requested, drive-by refactoring during fixes, silent picks among multiple interpretations. Use when reviewing or writing code involving design patterns, configurable options, or framework-style abstractions, or when the user invokes "/karpathy-examples". Trigger words include "안티패턴", "오버엔지니어링", "리팩토링 검토", "추상화 과한가".
---

# karpathy-examples

Concrete anti-patterns derived from [Karpathy's LLM coding observations](https://x.com/karpathy/status/2015883857489522876). Match these patterns to recognize over-engineering before committing.

The global Codex policy gives the abstract *why*. This skill gives the concrete
*what does it look like*.

## 1. Over-abstraction for single-use

❌ ABC + Strategy pattern for a one-line calculation:

```python
class DiscountStrategy(ABC):
    @abstractmethod
    def calculate(self, amount: float) -> float: ...

class PercentageDiscount(DiscountStrategy):
    def __init__(self, percentage): self.percentage = percentage
    def calculate(self, amount): return amount * (self.percentage / 100)
```

✅ Just the function:

```python
def calculate_discount(amount: float, percent: float) -> float:
    return amount * (percent / 100)
```

Add abstraction only when multiple types are *actually* needed *now*. Refactor when the second case appears.

## 2. Speculative options / flexibility

❌ Save function with cache/notify/validate/merge options not requested:

```python
def save(self, user_id, prefs, merge=True, validate=True, notify=False, cache=None): ...
```

✅ Save the prefs:

```python
def save_preferences(user_id: int, prefs: dict) -> None:
    db.execute("UPDATE users SET preferences = ? WHERE id = ?", (json.dumps(prefs), user_id))
```

## 3. Drive-by refactoring

❌ Bug fix that also reformats unrelated code, renames variables, "improves" comments.

✅ Change only lines needed for the fix. Mention unrelated issues without acting on them.

## 4. Silent interpretation picks

❌ "Make the search faster" → assume caching, write 200 lines of optimization without asking.

✅ Surface 2–3 interpretations (latency / throughput / perceived speed). Ask which matters. Define verifiable target before writing code.

## How to use this skill

- **Auto-trigger**: when about to write code involving abstractions, configurable options, multi-pattern handlers, or vague requirement words ("flexible", "extensible", "future-proof", "make X faster/better")
- **Explicit invoke**: `/karpathy-examples` to load anti-pattern reference for a code review pass
- **Companion**: `<coding_principles>` baseline (always loaded) handles the rule; this skill handles the recognition
