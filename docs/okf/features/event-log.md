---
type: Feature
title: Event log
description: On-device diagnostic log for bug reports.
resource: web/eventlog.js
tags: [debug]
timestamp: 2026-09-19T00:00:00Z
---
The "log" link under the title. Kept in localStorage, last 300 entries: visibility/focus/blur, `pageshow`/`pagehide`, `freeze`/`resume`, online/offline, freshness checks and results, sends, retries, conflicts, tree loads ([sync](sync-model.md)). Newest first with gaps since the previous entry (a big gap = page suspended). Copy button for bug reports. Event names and short details only, never todo titles.
