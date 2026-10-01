(() => {
  const DATABASE = "article-to-kindle-preview";
  const STORE = "captures";
  const RETENTION_MS = 60 * 60 * 1000;

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DATABASE, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Could not open preview storage."));
      request.onblocked = () => reject(new Error("Preview storage is busy in another tab."));
    });
  }

  function transactionDone(transaction) {
    return new Promise((resolve, reject) => {
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error || new Error("Could not save the article preview."));
      transaction.onabort = () => reject(transaction.error || new Error("Article preview storage was interrupted."));
    });
  }

  function randomId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return [...crypto.getRandomValues(new Uint8Array(16))]
      .map(value => value.toString(16).padStart(2, "0")).join("");
  }

  function removeExpired(store) {
    const cutoff = Date.now() - RETENTION_MS;
    const request = store.openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return;
      if (!cursor.value || cursor.value.createdAt < cutoff) cursor.delete();
      cursor.continue();
    };
  }

  async function saveCapture(capture) {
    const database = await openDatabase();
    const transaction = database.transaction(STORE, "readwrite");
    const done = transactionDone(transaction);
    const store = transaction.objectStore(STORE);
    removeExpired(store);
    const id = randomId();
    store.put({ capture, createdAt: Date.now() }, id);
    try {
      await done;
      return id;
    } finally {
      database.close();
    }
  }

  async function consumeCapture(id) {
    const database = await openDatabase();
    const transaction = database.transaction(STORE, "readwrite");
    const done = transactionDone(transaction);
    const store = transaction.objectStore(STORE);
    removeExpired(store);
    let record;
    const requested = new Promise((resolve, reject) => {
      const request = store.get(id);
      request.onsuccess = () => {
        record = request.result;
        if (record) store.delete(id);
        resolve();
      };
      request.onerror = () => reject(request.error || new Error("Could not load the article preview."));
    });
    try {
      await Promise.all([requested, done]);
    } finally {
      database.close();
    }
    if (!record || record.createdAt < Date.now() - RETENTION_MS) return null;
    return record.capture;
  }

  globalThis.ArticleCaptureStore = { consumeCapture, saveCapture };
})();
