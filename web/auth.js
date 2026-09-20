// Google sign-in via Firebase Auth. Wraps window.fetch so every /todos request
// carries the user's ID token; the server only accepts one Google account.
(function () {
  const cfg = window.NOW_CONFIG && window.NOW_CONFIG.firebase;
  if (!cfg) {
    // No web/config.js: say so instead of failing silently (see web/config.example.js).
    const overlay = document.getElementById("signin");
    document.getElementById("signin-message").textContent =
      "This deployment has no web/config.js (Firebase web config). See web/config.example.js.";
    document.getElementById("signin-button").hidden = true;
    overlay.hidden = false;
    return;
  }
  const hosting = window.NOW_CONFIG.hostingDomain;
  // On the Hosting domain, run the sign-in handler same-origin: iOS Safari
  // partitions storage, so a redirect back from another domain loses the result.
  // Elsewhere fall back to the default domain (registered on the OAuth client).
  const config = { ...cfg, authDomain: hosting && window.location.host === hosting ? hosting : cfg.authDomain };

  firebase.initializeApp(config);
  const auth = firebase.auth();
  const nativeFetch = window.fetch.bind(window);

  const overlay = document.getElementById("signin");
  const message = document.getElementById("signin-message");
  const button = document.getElementById("signin-button");
  const signOut = document.getElementById("signin-signout");

  function showSignIn(text, { canSignOut } = {}) {
    message.textContent = text || "";
    signOut.hidden = !canSignOut;
    button.hidden = !!canSignOut;
    overlay.hidden = false;
  }

  const firstState = new Promise((resolve) => {
    const off = auth.onAuthStateChanged((user) => {
      off();
      resolve(user);
    });
  });

  firstState.then((user) => {
    if (!user) showSignIn("");
    // Later sign-ins (popup or redirect return) reload so the app boots signed in.
    auth.onAuthStateChanged((next) => {
      if (next && !user) window.location.reload();
    });
  });

  button.addEventListener("click", async () => {
    const provider = new firebase.auth.GoogleAuthProvider();
    const useRedirect = window.navigator.standalone === true ||
      /iPhone|iPad|iPod/.test(navigator.userAgent);
    try {
      if (useRedirect) await auth.signInWithRedirect(provider);
      else await auth.signInWithPopup(provider);
    } catch (e) {
      message.textContent = "Sign-in failed: " + (e.message || e.code);
    }
  });

  signOut.addEventListener("click", async () => {
    await auth.signOut();
    window.location.reload();
  });

  auth.getRedirectResult().catch((e) => {
    showSignIn("Sign-in failed: " + (e.message || e.code));
  });

  function isApiRequest(input) {
    const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
    return url.origin === window.location.origin &&
      (url.pathname === "/todos" || url.pathname.startsWith("/todos/") || url.pathname.startsWith("/push/"));
  }

  async function withToken(input, init, forceRefresh) {
    const user = (await firstState) && auth.currentUser;
    if (!user) throw new Error("Sign in required");
    const token = await user.getIdToken(forceRefresh);
    const headers = new Headers(init.headers || {});
    headers.set("Authorization", "Bearer " + token);
    return nativeFetch(input, { ...init, headers });
  }

  window.fetch = async function (input, init = {}) {
    if (!isApiRequest(input)) return nativeFetch(input, init);
    let response = await withToken(input, init, false);
    if (response.status === 401) response = await withToken(input, init, true);
    if (response.status === 403) {
      showSignIn("This account isn't allowed to use this app.", { canSignOut: true });
    }
    return response;
  };
})();
