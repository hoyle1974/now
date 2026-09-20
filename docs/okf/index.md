---
type: Index
title: now — knowledge bundle
description: Curated knowledge about the "now" todo app, in Open Knowledge Format v0.1.
tags: [okf, index]
timestamp: 2026-09-19T00:00:00Z
---
# now

A personal todo app: FastAPI + vanilla-JS frontend, Firestore on GCP Cloud Run.
This directory is an [Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)
bundle: markdown files with YAML frontmatter (`type` is the only required field),
linked to each other with ordinary markdown links. It is checked in and curated
like code.

## Keeping it in sync (rules)

1. **Update it in the same change.** Any change that alters behaviour, the data
   model, an API route, the sync protocol, deployment or testing must update the
   affected concept files and bump their `timestamp`, in the same commit.
2. **Log it.** Add a dated line to [log.md](log.md) for every update.
3. **Link, don't duplicate.** State a fact in one file and link to it elsewhere.
4. **Code wins.** If a file here disagrees with the code, fix this file; if the
   code is wrong, fix the code and then this file.
5. **New concept = new file** with a `type`, listed in the section below.
6. These rules are enforced for Claude by the project `CLAUDE.md`.

## Concepts

- Architecture: [stack](architecture/stack.md), [code map](architecture/code-map.md)
- Data: [Todo](data/todo.md), [Firestore collections](data/firestore.md)
- API: [routes](api/routes.md)
- Features: [sync model](features/sync-model.md), [ordering and nesting](features/ordering-nesting.md),
  [due time](features/due-time.md), [next up](features/next-up.md),
  [repeating todos](features/repeating-todos.md), [fields: color, links, dependencies](features/fields.md),
  [trash, clear completed, archive](features/trash-archive.md), [auto-done and done-sink](features/auto-done.md),
  [event log](features/event-log.md)
- Ops: [testing](ops/testing.md), [deploy](ops/deploy.md), [Lock Screen widget](ops/widget.md)
