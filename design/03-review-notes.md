# Review notes — Yann on the v1 spec (2026-07-20)

Yann's remarks, preserved verbatim, with how each was resolved. The remarks were annotated
inline on `02-spec.md`; the spec has been rewritten and now reads clean.

---

### R1 — on the narrow scope

> "Je comprends pas pourquoi on se limite aux documentations de spécification de design et
> product et produit. C'est effectivement certainement l'essentiel de ce qui va m'intéresser
> mais pourquoi on n'appliquerait pas ce skill sur n'importe quelle communication."

**Resolved: accepted, scope widened to all agent↔user communication.**

The narrowing was my error — I turned "specs/design/product are what I care about" into an
exclusion. Yann's phrasing already contains the right distinction: those documents are
*"certainement l'essentiel de ce qui va m'intéresser"* (where the value concentrates) but that
is emphasis, not a boundary. See [`01-scope.md`](01-scope.md).

Knock-on design changes: the concept model becomes domain-agnostic; it moves to user-global
storage rather than per-project; and the always-on injection layer becomes the backbone,
because a description-triggered skill cannot fire on "any communication."

---

### R2 — on subtractive positioning

> "Je suis aligné avec cette position, ça correspond vraiment à une approche minimaliste qui me
> semblait mieux correspondre à une utilisation frugale de la capacité d'attention de
> l'utilisateur, et le fait qu'on ajuste le discours à l'aide d'une représentation du modèle
> mental de l'utilisateur est effectivement un moyen alors que le point est vraiment de
> minimiser le bruit. Je suis complètement d'accord."

**Resolved: confirmed, no change.**

Confirms the positioning that came out of [pass 3b](../research/04-adaptive-explanation-evidence.md):
minimising noise is the *point*; the mental-model representation is a *means*; frugal use of
the user's attention is the goal. This is now the spec's load-bearing frame and should not
drift back toward "personalised explanations" in later revisions.

---

### R3 — on where the scope came from

> "Par contre le scope, je ne comprends pas d'où ça sort, moi j'aimerais un skill qui marche
> dans toute situation d'interaction entre l'agent et un utilisateur, parce que je trouve que
> d'une manière générale, il faut essayer d'améliorer la clarté de la communication entre un
> agent et un utilisateur."

**Resolved: same as R1.** The scope came from my over-reading of an earlier remark about code;
it has been replaced with universal scope and the provenance of the error is documented in
[`01-scope.md`](01-scope.md) so it does not recur.
