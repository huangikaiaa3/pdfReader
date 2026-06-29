# Retrieval Evaluation Notes

## Purpose

This note captures a compact checklist for judging whether document retrieval is working well enough before deeper tuning.

## Current Scope

- single-document retrieval
- question embedding with Gemini
- pgvector cosine-distance ranking
- top-k chunk return path
- grounded answer endpoint built on retrieved matches

## Quick Evaluation Checklist

For each test question, inspect:

- whether the expected chunk appears in the top 1 results
- whether the expected chunk appears in the top 3 results
- whether the top chunk page range makes sense
- whether the answer endpoint uses the strongest chunk as evidence
- whether irrelevant questions fall into insufficient-context behavior

## Suggested Transcript Questions

Use `columbia_eTranscript.pdf` for the first manual pass:

- What is the cumulative GPA?
- What degree program is this transcript for?
- What major is listed on the transcript?
- Which course titles appear in Fall 2022?
- What school issued this transcript?

## Suggested Checks

- If a direct factual question is asked, the top match should usually contain the answer verbatim.
- Returned distances should generally look lower for strong matches than for obviously unrelated chunks.
- If the strongest match is weak or generic, the answer endpoint should prefer insufficient-context fallback over speculation.
- Citations should map back to the chunk id and page range of the strongest supporting evidence.

## Current Manual Observation

- The question `What is the cumulative GPA?` returned the page 2 transcript chunk that explicitly contains `Cumulative GPA: 3.582`.
- The grounded answer endpoint returned `Cumulative GPA: 3.582` with that chunk as the strongest supporting match.

## Next Evaluation Improvements

- add a small golden set of question -> expected page/chunk pairs
- compare top 1 versus top 3 recall
- record a few intentionally unanswerable questions
- tune weak-context threshold only after several manual checks
