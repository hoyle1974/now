// Persists the sync outbox so unsent edits survive a reload or the OS killing
// the tab. IndexedDB first (async, off the render path), then localStorage,
// then memory; every access is wrapped because private windows and blocked
// site data make each of them throw.
(function (root) {
  "use strict";

  const DB_NAME = "todo-sync";
  const STORE = "outbox";
  const KEY = "ops";
  const LS_KEY = "todo-sync-outbox";

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function idbRequest(db, mode, fn) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(req ? req.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  function create() {
    let memory = [];
    let dbPromise = null;
    const db = () => {
      if (!dbPromise) dbPromise = openDb();
      return dbPromise;
    };

    async function load() {
      try {
        const ops = await idbRequest(await db(), "readonly", (s) => s.get(KEY));
        return ops || [];
      } catch (e) {
        try {
          return JSON.parse(localStorage.getItem(LS_KEY) || "[]");
        } catch (e2) {
          return memory;
        }
      }
    }

    async function save(ops) {
      memory = ops;
      try {
        await idbRequest(await db(), "readwrite", (s) => s.put(ops, KEY));
      } catch (e) {
        try {
          localStorage.setItem(LS_KEY, JSON.stringify(ops));
        } catch (e2) {
          // Memory only: edits still sync, they just won't survive a reload.
        }
      }
    }

    return { load, save };
  }

  root.IdbStore = { create };
})(typeof self !== "undefined" ? self : this);
