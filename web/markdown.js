// Markdown for note bodies. html is off, so a note cannot inject tags.
// markdown-it (MIT) is loaded first: vendor/markdown-it.min.js.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./vendor/markdown-it.min.js"));
  } else {
    root.Markdown = factory(root.markdownit);
  }
})(typeof self !== "undefined" ? self : this, function (markdownit) {
  "use strict";

  const md = markdownit({ html: false, linkify: false, breaks: true });

  function render(src) {
    return md.render(String(src == null ? "" : src));
  }

  return { render };
});
