# Analogy and technical-writing science (pass 3, strand 1 of 3)

*Targeted follow-up on strands the two deep-research passes left uncovered. Complements
[pass 1](01-state-of-the-art.md) (cognitive science, user modeling) and
[pass 2](02-communication-frameworks.md) (documentation structure, HAI guidelines).*

## Headline

Two results here overturn common practice:

1. **Appending a caveat to an analogy does not work.** The analogical core is what survives in
   memory, warnings included. This kills the reflex "here's an analogy, though it breaks down
   at X" — the standard move in agent explanation.
2. **Readability scores must never be a target.** Improving the score can *worsen*
   comprehension, because the connective tissue that helps readers is exactly what the
   formulas penalize.

And one result is a strong positive: **Carroll's minimalism is among the best-evidenced
findings in technical communication** — 40% less learning time, 2.7× task completion.

## Strand 1 — Analogy

### The theory: analogy maps relations, not appearances

Gentner's structure-mapping theory
([PDF](https://courses.csail.mit.edu/6.803/pdf/gentner.pdf)): *"Analogies tend to match
connected systems of relations… A matching set of relations interconnected by higher order
constraining relations makes a better analogical match than an equal number of matching
relations that are unconnected to each other. The systematicity principle captures a tacit
preference for coherence and causal predictive power in analogical processing."*

The relation/attribute split is formal, not stylistic: *"in analogy, only relational
predicates are shared, whereas in literal similarity, both relational predicates and object
attributes are shared."* Matches sharing appearance but no relations are **mere-appearance
matches**, which *"are of course sharply limited in their predictive utility… they often occur
among children and other novices and may interfere with their learning."*

**This gives a hard, mechanical test an agent can apply to itself**: if the analogy's appeal
is "both are shaped like X" rather than "A does X to B, causing C", it is a mere-appearance
match and will harm rather than help.

### When analogies mislead: eight failure modes

Spiro, Feltovich, Coulson & Anderson studied misconceptions in medical students and built a
typology of eight ways analogies induce them
([ERIC ED301873](https://files.eric.ed.gov/fulltext/ED301873.pdf)). All eight share two
features: *"(a) the source (or base) domain information in the analogy is inadequate or
potentially misleading for understanding the target domain (the topic), and (b) in practice,
the knowledge acquired about the topic is reduced to just that information mapped by
(inadequate) analogy from the source domain."*

1. **Indirectly misleading properties** — a salient source trait, incidental to the point,
   poisons a parallel target trait.
2. **Missing properties** — a target aspect with no source counterpart drops out of the
   learner's model entirely.
3. **Exportation of base properties** — a source feature with no target analogue gets exported
   anyway; *"a non-existent 'slot' is created in the topic."*
4. **Directly misleading properties** — a non-salient source value wrongly assigned to target.
5. **Surface description masking causation** — *"learners are susceptible to either filling in
   a convenient but incorrect causal account of their own, or just leaving the causal
   mechanism unexplained, as a kind of 'black box.'"*
6. **Wrong grain size** — pitched at a magnification that hides the relevant mechanism.
7. **Everyday connotations of technical terms** — the ordinary-language sense is
   *"overextended to their technical use."*
8. **Connotatively loaded informal descriptors** — loose words smuggle in wrong models.

Types 3, 5 and 7 are rampant in software explanation. (Type 7 especially: "thread", "lock",
"stream", "pipe", "container" all invite their everyday sense.)

### The critical finding: caveats do not work

> *"The reductive force of analogies appears to be so great that it is not enough merely to
> tell people what the limitations of an analogy are. When teachers or texts provide such
> caveats for an instructional analogy, the result over time tends to be the same: The
> analogical core is what is retained."*
>
> — and in conclusion: *"even very detailed warnings are probably not sufficient by
> themselves."*

**This directly contradicts standard agent practice.** "Think of it like X — though the
analogy breaks down because Y" feels responsible and is close to useless: the reader keeps X
and discards Y.

The prescribed remedy is **multiple, integrated analogies**: *"combat the power of a limited
analogy with another powerful analogy that counteracts the limitations of the earlier one"* —
the second chosen specifically to repair *"(a) information that is missing from the source,
(b) information in the source that is misleading about the topic, and (c) information that is
inappropriately focused in the source."* Cost flagged by the authors: multiple analogies
*"introduce additional cognitive load"* — which must be weighed against pass 1's load budget.

### Source familiarity is about the relation, not the object

Learners *"are not always familiar with those features that provide the similarity to the
target"*
([review](https://www.psychologyinaction.org/analogy-based-learning-in-the-classroom-implementing-strategies-to-promote-conceptual-understanding-and-performance/)).
Knowing what a mailbox *is* is not knowing its queuing semantics. This sharpens pass 1's rule
that chunking must land on existing schemas: the KB must record familiarity with the
*relational structure*, not merely the term.

### Rules to encode (analogy)

22. **Relation test before deploying**: state the relational structure being mapped (`A does X
    to B, causing C`). If only shared appearance can be articulated, drop the analogy.
23. **Never ship a single analogy for a genuinely complex concept** — pair it with a second
    chosen to repair the first's specific defect.
24. **Treat "caveat appended" as insufficient.** Either correct the defect with a second
    mapping, or state the mechanism directly in non-analogical terms alongside it.
25. **Audit against the eight failure types**, especially #3 (exporting a feature the target
    lacks), #5 (black-box causation), #7 (everyday connotation of a technical term).
26. **Verify source familiarity for the relation, not the object.**

## Strand 2 — Technical writing beyond Diátaxis

### Carroll's minimalism: strong experimental support

The minimal manual *"is briefer; it helps learners to coordinate their attention between the
system and the manual; it specifically trains error recognition and recovery; and it better
supports reference use after training"*
([Carroll, Smith-Kerker, Ford & Mazur-Rimetz, *The Minimal Manual*, HCI 3(2), 1987](http://swcarpentry.github.io/swc-releases/2017.02/instructor-training/files/papers/carroll-minimal-manual-1987.pdf)).

Experiment 1, verbatim:
- *"Overall, the MM subjects required 40% less learning time than the SS subjects,
  t(17) = 3.06, p < .01."*
- *"Overall, the MM subjects accomplished 2.7 times as many performance subtasks as the SS
  subjects, t(16) = 3.63, p < .01."*
- *"The MM subjects were more than twice as efficient as the SS subjects, t(16) = 2.90,
  p < .01."*
- The advantage **persisted into advanced material both groups studied from a common manual**
  — the minimal manual improved onward learning, not just its own throughput.

Experiment 2: MM learners *"completed 52% more subtasks,"* *"achieved 93% more per unit of
time,"* spent *"29% less"* time reading, and *"successfully used recommended error recovery
methods 60% more often."*

Note how well this converges with pass 1: cutting verbiage is the same lever as reducing
extraneous cognitive load, arrived at from an entirely different tradition.

### Plain language: standardized, supported, weaker evidence

**ISO 24495-1:2023** defines four governing principles — readers get **what they need**
(relevant), can **easily find** it (findable), **easily understand** it (understandable), and
**easily use** it (usable) ([ISO](https://www.iso.org/standard/78907.html)). Crucially, the
standard defines plain language by **reader outcome, not text features** — it is not a
word-length rule. US guidance: [plainlanguage.gov](https://www.plainlanguage.gov/guidelines/)
(Plain Writing Act 2010).

Evidence is real but domain-scattered: a multimethods randomized trial found plain-language
versions improved adults' understanding of health recommendations
([J Clin Epidemiol](https://www.sciencedirect.com/science/article/pii/S0895435623003037)).
Treat the general claim as supported; treat numeric claims from advocacy material as
unverified.

### Readability formulas: never a target

The decisive critique is Ginny Redish's
([PDF](https://redish.net/wp-content/uploads/Redish_on_Readability_Formulas.pdf)):

- **They measure countable surface features only**: *"the features included in the published
  formulas are usually chosen as much for how easy they are to count as for their predictive
  value… Most formulas select only one or two features to count: sentence length and/or
  syllables per word."*
- **Improving the score barely moves comprehension**: Klare (1976) reviewed 36 studies —
  *"Only about half succeeded and to improve comprehension they had to change the readability
  scores by an average of 6.5 grade levels."*
- **The killer datum**: Charrow & Charrow revised jury instructions and measured comprehension.
  *"Comprehension went up. But… In many cases, their revisions got better comprehension scores
  but worse readability scores. (This happened primarily because they added words to show the
  relationships among the information items.)"* **The connective tissue that helps readers is
  what the formulas penalize.**
- **Gaming is explicit misuse**: *"Klare, Flesch, Gunning, and all the other developers of
  readability formulas insist that the formulas are not to be used for revision."* Klare's
  analogy: *"expecting comprehension to improve by writing to a readability formula is like
  lighting a match under a thermometer to warm up a room."*
- Formulas also break on lists, tables and non-prose layouts, scoring bulleted content as long
  sentences — directly relevant to agent output, which is list-heavy.

One legitimate use, conceded: a *very poor* score is *"a red flag"* — but *"a good score does
not mean you have a usable or useful document."*

### Rules to encode (writing)

27. **Open with a real task, not a concept inventory.** Cut preamble that delays the reader's
    first action (Carroll).
28. **Budget explicit space for error recognition and recovery** — the largest single
    differentiator in Carroll's data (60% more successful recovery). Say what going wrong
    looks like and how to get back.
29. **Acceptance criteria = ISO 24495-1's four checks**: relevant, findable, understandable,
    usable. Reader outcome, not text metrics.
30. **Never target a readability score.** Explicitly permit longer sentences when the extra
    words are connective tissue showing relationships — that is what improves comprehension
    while worsening the score. A bad score may be used as a one-way smoke alarm only.
31. **Prefer cutting to simplifying.** "Slash the verbiage" is the empirically-backed lever;
    substituting short words for accurate technical terms is not, and risks Spiro's failure
    type #7.

## Confidence summary

| Claim | Status |
|---|---|
| Structure-mapping / systematicity | Well-established theory, large literature |
| Analogies induce specific misconception types | Empirically observed (medical students); typology descriptive, not validated type-by-type |
| Caveats insufficient; multiple analogies as antidote | Observation + argued prescription; the *remedy* is less validated than the *problem* |
| Minimalism gains (40%, 2.7×) | **Strong** — controlled experiments, significant, replicated in-paper |
| Plain language improves comprehension | Supported incl. RCT evidence; effect sizes vary by domain |
| Readability formulas invalid as targets | **Strong** — converging critiques plus counter-evidence (Charrow) |
| Glynn Teaching-With-Analogies model | Popular, sensible, derived from textbook analysis; not strongly validated |
