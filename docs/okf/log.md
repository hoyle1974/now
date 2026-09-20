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
- 2026-09-19: UI round 3: validation/error toast now above full-screen sheets (z-index 120); text-only actions (Cancel, Add link, Remove, Undelete, Trash, More, log, Undo) are tonal/pill buttons with 44pt targets or hit-slop; new web/sparkle.js (confetti on completion, bigger burst when everything is done, skipped under reduced motion); gradient send button, floating empty-state icon, press feedback. Asset version v=35. No behaviour/data/API change.
- 2026-09-19: APP_VERSION bumped to 35 to match asset ?v=35 (it is what makes open clients reload).
- 2026-09-19: Header shows a device-local "N done today" counter (localStorage now.doneToday, resets daily; todos carry no completion time); repeat unit labels are singular for every=1. APP_VERSION/asset v=36.
- 2026-09-19: Accent themes (Indigo/Ocean/Berry/Forest/Sunset) and an opt-in synthesized completion sound in the header More panel (web/themes.js; localStorage now.theme / now.sound). APP_VERSION/asset v=38.
- 2026-09-19: Mascot "Nudge" (web/mascot.js): peeks up from behind the add bar after 25-55s idle, blinks, says a list-aware line, ducks away; cheers when everything is done; tap to giggle; off under reduced motion; toggle in More (localStorage now.mascot). APP_VERSION/asset v=39.
- 2026-09-19: Shake to summon the mascot (accelerometer, 3 hard jolts within 0.9s, 3s cooldown); iOS needs the More panel's "Shake to summon" tap to grant motion permission (asked again after a reload); Android/desktop listen automatically. APP_VERSION/asset v=40.
- 2026-09-19: Shake detector now measures each reading's distance from gravity (>7 m/s2, three swings 100ms+ apart within 1.4s) since per-sample deltas were too small at 60Hz; More panel shows live motion strength on the Shake button; tapping the Todos title 3x also summons the mascot. APP_VERSION/asset v=41.
- 2026-09-19: Mascot is positioned from the measured composer height, above it and clipped at its top edge (z-index 35) so the add bar can never hide him; page bottom padding uses max(measured, 84px + safe-area) + 32px so Trash clears the bar; --composer-h re-measured on resize/orientation/visualViewport. Mascot voice (Sound.sfx: peek chirp, blink blip, bee-boop, boop, giggle, cheer) plays only when Sound is on; audio unlocks on first tap. Shake detector uses deviation from gravity. APP_VERSION/asset v=43.
- 2026-09-19: Mascot fully hidden when away (translate past the clip line + visibility hidden, so the antenna tip no longer shows); speech bubble is clamped inside the viewport with its tail still pointing at him (--bubble-shift). APP_VERSION/asset v=45.
- 2026-09-19: Mascot reactions (Mascot.react: 10s global gap, per-topic cooldowns, skipped when busy/hidden/up): back online, batch synced (>=3), offline, changes from another device (not at launch), first add and every 5th, done-today milestones (3/5/10/15/20/30), completing a repeating todo, welcome back after 20+ min away, once-a-day time-of-day greeting (localStorage now.greeted). APP_VERSION/asset v=46.
- 2026-09-19: sync client review fixes (delete If-Match, auth retry, 404 narrowing, undelete parent, rebuild moves, freshness retry, viewer fixes); version 47.
- 2026-09-19: Backend review fixes: move up/down maps only deliberate refusals (MoveError) to 4xx; attachment upload deletes its blob unless the stored todo lists it, orphan-blob sweep added to the daily archive run; archive moves in transactions with a re-read and rev bump, atomic last_run claim, naive timestamps read as UTC; next-up normalizes aware dues; 413 from Content-Length before reading uploads; removed legacy /parent/{id} route and dead code.
- 2026-09-19: API 404s carry explicit detail text (todo not found / attachment not found / parent not found) so the client can tell an item gone from a missing route.
- 2026-09-19: Edit sheet gets a "Pick date" chip and a tappable date field (due-time.md); app v48.
