---
type: Log
title: Change log
description: Dated record of updates to this bundle.
timestamp: 2026-09-19T12:00:00Z
---
- 2026-09-19: Initial bundle drafted from README.md and the code (app/, web/).
- 2026-09-19: Added image attachments (features/attachments.md); updated Todo, routes, code map, stack, trash-archive, deploy, testing.
- 2026-09-19: Documented the full-screen todo viewer (features/fields.md, code map).
- 2026-09-19: Sync/API fixes: no coalescing into sent ops, tmp ids remapped in link lists, archived link ids stay editable, X-Txn-Id validated, txn_log kept 30 days.
- 2026-09-19: UI polish from a mobile review: row menu gets scroll room above the composer on short pages (body.menu-room), todo picker clears its search after a pick, debug links larger and higher contrast, asset version bumped to v=28. No behaviour/data/API change, so no other OKF files needed.
- 2026-09-19: UI polish round 2: completed rows sink once after the last quick tap settles (1.4s); "Clear N completed" label with tooltip; diagnostics links (log, icon badge) behind a header "More" toggle; --label-3 and disabled send button contrast raised; list gets bottom room while a toast shows. Asset version v=30. No behaviour/data/API change.
