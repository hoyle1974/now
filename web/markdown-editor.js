// EasyMDE (MIT) on a note's content textarea. The preview uses Markdown.render,
// the same renderer as the viewer, so what you preview is what you read.
const MarkdownEditor = (() => {
  function attach(textarea) {
    if (typeof EasyMDE !== "function") return null;
    const editor = new EasyMDE({
      element: textarea,
      spellChecker: false,
      status: false,
      minHeight: "50vh",
      autofocus: false,
      placeholder: "Write…",
      previewRender: (plain) => (typeof Markdown !== "undefined" ? Markdown.render(plain) : ""),
      toolbar: ["bold", "italic", "heading", "|", "quote", "unordered-list", "ordered-list", "|", "link", "preview"],
    });
    return {
      value: () => editor.value(),
      refresh: () => editor.codemirror.refresh(),
    };
  }

  return { attach };
})();
