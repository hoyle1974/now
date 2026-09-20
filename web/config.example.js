// Per-deployment client config. Copy to web/config.js (git-ignored) and fill in,
// or let scripts/init.sh write it from `firebase apps:sdkconfig`. The Firebase web
// config is not a secret: it only names your project; access is enforced server-side.
window.NOW_CONFIG = {
  firebase: {
    apiKey: "",
    authDomain: "YOUR-PROJECT.firebaseapp.com",
    projectId: "YOUR-PROJECT",
    messagingSenderId: "",  // the project number; FCM push needs it
    appId: "",
  },
  // Optional: your Firebase Hosting domain. On it, sign-in runs same-origin, which
  // iOS Safari needs (it partitions storage, so a redirect from another domain loses
  // the result). Elsewhere the default authDomain above is used.
  hostingDomain: "",
};
