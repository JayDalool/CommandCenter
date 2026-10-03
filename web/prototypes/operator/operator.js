/* Direction A — OPERATOR. Dense operations console: one grid, hairline rules,
 * tables everywhere, no panels. Uses the shared renderers almost unchanged;
 * the character is in operator.css. */
(function () {
  const shell = () => `
    <div class="app">
      <aside class="rail" aria-label="Navigation">
        <div class="brand"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">Command Center</span></div>
        <nav id="cc-nav" aria-label="Screens"></nav>
        <div id="cc-railfoot" class="rail-foot"></div>
      </aside>
      <div class="main">
        <header id="cc-top" class="top"></header>
        <div id="cc-banner"></div>
        <main id="cc-screen" class="screen" tabindex="-1"></main>
      </div>
    </div>`;

  if (window.CC && CC.start && typeof document !== "undefined" && document.getElementById("cc-app")) {
    CC.start({ id: "operator", shell });
  }
  window.CC_VARIANTS = Object.assign(window.CC_VARIANTS || {}, { operator: { id: "operator", shell } });
})();
