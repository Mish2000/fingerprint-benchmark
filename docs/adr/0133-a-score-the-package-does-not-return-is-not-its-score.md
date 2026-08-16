# A score the package does not return is not its score

## Status

Accepted, implemented.

## Context

`fingerprintMatcher` 1.0.6 is, on paper, the cleanest Algorithm 5 candidate this
project has seen. MIT, on PyPI, one pure-Python file, 3,008 bytes of sdist and
3,126 of wheel with fixed digests, OS-independent, no vendor, no checkpoint, no
licence clock. Its documented entry point is exactly the right shape:
`match_fingerprints(image1, image2)`.

Its published module contains this:

```python
match_ratio = len(match_points) / keypoints_count

if match_ratio > 0.95:
    print(f"The two images are matched")
    print("percentage(%) of match: ", len(match_points) / keypoints_count * 100)
    result = cv2.drawMatches(...)
else:
    print("Sorry, the fingerprints do not match.")
```

`match_fingerprints` has no `return` statement carrying a value; its own
docstring declares `Returns: None`; the only observable is text on stdout; and
`0.95` is a decision threshold chosen by its author and compiled into the
function. The package's own README confirms the shape — its usage example calls
`fingerprint_matcher.match_fingerprints("path/to/image1", "path/to/image2")` as a
bare statement, with nothing on the left of an `=`.

So the similarity ratio exists. It is computed, compared, and thrown away. In the
matching branch a percentage of it reaches stdout; in the non-matching branch no
number is printed at all.

This creates a temptation the four preceding stages did not: the number is
*right there*, it is obviously higher-is-more-similar, and two lines would
recover it. Either re-implement the function to return `match_ratio`, or run the
package as a subprocess and parse what it prints. Both would produce six thousand
plausible scores by tomorrow.

## Decision

**A benchmark may only record a score its candidate returns.** If the published
entry point does not hand back a value, the candidate has no raw score, and the
stage closes with `FINGERPRINTMATCHER_SCORE_CONTRACT_FAIL`.

Specifically refused, and each one denied in the marker as a checked field:

- `upstream_function_reimplemented` — rewriting `match_fingerprints` to return
  its ratio produces a number authored by fpbench that resembles one the package
  computes. The resemblance is the danger: nothing downstream would show it.
- `stdout_parsed_for_a_score` — the printed percentage only exists above the
  author's threshold, so scraping it yields a column that is null for every
  comparison the package called a non-match. That is not a score distribution; it
  is a decision with a decoration.
- `score_reconstructed_by_fpbench` — the general form of both.

The gate is decided by parsing the published module, before anything is
installed or executed. `returns_native_scalar_before_decision` is derived from
the count of value-carrying `return` nodes, the internal threshold is read out of
the `if`, and the ratio expression is unparsed from the assignment. None of it is
asserted by hand.

**A failed score contract may not publish a score direction.**
`build_stage17a_finalization` raises if one is present, and
`verify_stage17a_evidence` refuses committed evidence that carries one. The ratio
is transparently higher-is-more-similar and writing that down would describe a
number the package never publishes.

**The authority is the distribution, not the repository.** The project's GitHub
does not presently show `fingerprintmatcher.py` at its root, while PyPI
distributes a module that would actually execute. A qualification that read the
repository would be describing code nobody installs. The sdist and the wheel are
both opened and their modules compared, because a package whose two
distributions differ has no single answer to "what does it do".

## Alternatives

**Subclass and call the internals.** Rejected. There are no internals: the ratio
is a local in a function with no seam. Any access requires editing the function
body.

**Ask the author for a returning variant.** Rejected on ADR 0126's rule —
runnable without vendor action is a hard requirement, and an unreleased variant
is not an artifact. It remains the one act that would reopen this candidate, and
the evidence says so.

**Use `match_ratio > 0.95` as the algorithm's own decision and record booleans.**
Rejected, and this is the most seductive of the three. A boolean column cannot
enter the calibration phase every other algorithm is headed for: there is no
operating point to choose because the author already chose one, and no way to
compare it against SourceAFIS at 40 or NBIS at 40 or VeriFinger at 48. It would
also mean the benchmark's fifth algorithm is the only one whose threshold was set
by somebody who never saw SD300.

**Take a later or earlier version.** Not applicable: 1.0.6 is the newest of six,
and the user's instruction pins it.

## Consequences

Stage 17A closes at G2 of 7 having installed nothing, executed nothing and opened
no SD300 image. It is the smallest stage in this project's history and it cost
one file read, which is the result the ordering was designed for: the previous
three candidate stages each built acquisition, runtime and route machinery before
discovering the candidate could not be used.

Algorithm 5 remains open. That is now five consecutive stages — 12A, 13A, 14A,
16A, 17A — with no fifth algorithm, and the pattern across them is worth stating:
three ended at a vendor, one at missing documentation, and this one at a package
that makes the decision the benchmark exists to make itself.

The general rule for the next candidate, and it should be checked first, before
acquisition machinery of any kind: **read the entry point and confirm it returns
a value.** A package that prints its answer is not a matcher this benchmark can
measure, however good its algorithm may be.
