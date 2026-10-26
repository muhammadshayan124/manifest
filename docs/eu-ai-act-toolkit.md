# EU AI Act toolkit: what is encoded, from where, and what it cannot do

## Sources

The reference data in [`src/manifest/act/data.py`](../src/manifest/act/data.py) was read on 2026-10-26 from
[artificialintelligenceact.eu](https://artificialintelligenceact.eu), an unofficial reproduction of Regulation (EU)
2024/1689: Article 5, Article 6, Article 53, Article 113, Annex III and Annex IV. The requirement summaries for
Articles 9-20, 26, 27, 43, 47-49, 72, 73 and 86 are written from the Regulation's structure and are paraphrases, not
quotations; each carries its citation so a reader can check it.

Anything that could not be confirmed from those pages is marked `verify` in the output. The two cases at the time of
writing: the Article 51(2) compute presumption (1e25 FLOPs; the page showed only the article title) and the Article
111(3) transitional date for models already on the market.

## What the classifier decides, and in what order

```text
scope (Art. 2, 3(1))      declared exemption / no EU nexus / not an AI system   -> out_of_scope
prohibited (Art. 5)       any declared practice without a claimed exception      -> prohibited
high-risk (Art. 6)        Annex I route (safety component AND third-party        -> high_risk
                          assessment), or an Annex III use case unless the
                          Art. 6(3) derogation is fully claimed AND no profiling
derogated (Art. 6(3)-(4)) Annex III use case, derogation fully claimed           -> not_high_risk_documented
transparency (Art. 50)    any Art. 50 trigger and nothing above                  -> transparency
otherwise                                                                        -> minimal
```

Layered on top, not tiers: general-purpose AI model duties (Chapter V) and AI literacy (Article 4).

Judgement calls are surfaced as warnings instead of being resolved silently:

* **Claimed Article 5 exceptions.** The system is not treated as prohibited, but the permitted remainder is classified
  high-risk under the Annex III point it falls into (5(1)(d) -> 6(d), (f) -> 1(c), (g) -> 1(b), (h) -> 1(a)), and the
  output demands legal review.
* **Partial derogation claims.** Claiming a condition without concluding "no significant risk" (or the reverse) is not a
  derogation; the system stays high-risk and says why.
* **Profiling.** Profiling of natural persons defeats the derogation unconditionally, as Article 6(3) provides.
* **"Obvious" AI interaction.** Suppresses Article 50(1) only when you declare it, and says that the test is the view of
  a reasonably well-informed, observant person.
* **Where permitted by law.** Annex III areas 1, 6 and 7 carry that qualifier and the output repeats it.

## Why the checklist refuses some things

* `done` requires evidence. A checkbox with no pointer to a document is the failure mode of every compliance tracker.
* The code scanner can contradict a claim but never make one. "No findings" is recorded as *not proof of compliance*;
  an Article 50(1)/(2) item marked `done` while the scanner reports a likely violation fails `--check`.
* Open items do not fail the default check, because failing on `todo` is how teams learn to switch the check off.

## Limits

* **Garbage in, garbage out.** The classification is a function of the profile. If a recruitment tool is described as
  "workflow software", it will be classified as minimal. The profile format lists every valid id so nothing has to be
  guessed, but it cannot stop someone declaring facts that are not true.
* **No legal conclusions.** Whether something is an "AI system", whether a derogation holds, whether an exception
  applies, and the scope of Annex III points are legal questions. The Commission's classification guidelines were due on
  2 February 2026 and may change how borderline cases are read.
* **Dates are a moving target.** The source shows the application dates as amended by the "Digital Omnibus" package
  (Annex III high-risk obligations on 2 December 2027, Annex I on 2 August 2028). Publication of those amendments in the
  Official Journal was not confirmed. `manifest act timeline` prints the dates with this caveat, and every
  classification repeats it.
* **Not covered:** the full set of deployer duties for specific sectors, harmonised standards (still being drafted),
  national implementation and penalties, importer and distributor obligations (Articles 23 and 24), and authorised
  representatives (Article 22).
* **Annex IV is a scaffold.** The documentation's substance (data provenance, validation results, risk analysis)
  comes from engineering work. The generator tells you what is missing; it cannot supply it.
