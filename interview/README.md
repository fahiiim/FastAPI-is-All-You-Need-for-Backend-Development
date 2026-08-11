# FastAPI Backend Interview Guide

The bank tests explanation, diagnosis, and tradeoff judgment. It is not a list of definitions to memorize.

## How to practice

For each question:

1. Give a 30 to 60 second answer.
2. Name one production failure or tradeoff.
3. Describe how you would test or observe the behavior.
4. Answer the follow-up without changing your original assumptions silently.

If a question is underspecified, state the requirement that changes the design. Senior interviews often evaluate whether you identify missing constraints before selecting technology.

## Banks

- [Beginner](beginner.md): Python web basics, HTTP, schemas, routes, dependencies, and CRUD.
- [Intermediate](intermediate.md): sessions, async, authentication, middleware, testing, Docker, Redis, and jobs.
- [Advanced](advanced.md): transactions, concurrency, performance, delivery guarantees, security, and observability.
- [Senior](senior.md): boundaries, failure economics, multi-tenancy, high traffic, migrations, and technical decisions.
- [Scenario-based](scenario-based.md): realistic incidents and design exercises with investigation paths.
- [Topic drills](topic-drills.md): short prompts grouped by Python, HTTP, data, security, testing, architecture, and operations.

## A useful answer shape

### Short answer

Answer the actual question in a few sentences. Name the primary decision.

### Deeper explanation

Explain the mechanism or guarantee. Distinguish concepts that are often conflated.

### Practical example

Describe a request, query, failure, or small implementation. Examples demonstrate that the definition has operational meaning.

### Senior-level discussion

State tradeoffs, failure cases, scaling behavior, security boundaries, or what evidence would change the choice.

### Common follow-ups

Prepare for the next layer rather than ending with a slogan.

## Evaluation rubric

| Signal | Weak | Strong |
| --- | --- | --- |
| Correctness | Repeats framework marketing | Names the actual protocol or runtime behavior |
| Scope | Assumes one universal context | States traffic, consistency, latency, and ownership assumptions |
| Failure awareness | Describes success path only | Covers timeout, duplicate, concurrency, and partial failure |
| Security | Adds auth as a final bullet | Defines identity, resource policy, tenant scope, and data exposure |
| Operability | Says "monitor it" | Names signals, thresholds, and an investigation path |
| Tradeoffs | Selects tools by popularity | Explains cost, alternatives, and revisit conditions |

## Whiteboard habit

For system-design questions, draw the synchronous path first. Mark every network boundary, state owner, transaction, and queue. Then add cache, replicas, and asynchronous processing only where a requirement demands them.

[Back to documentation map](../README.md)
