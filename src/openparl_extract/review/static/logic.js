/* Pure helper functions of the review page (no DOM). UMD-style so node can test them. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Logic = factory();
})(this, function () {
  "use strict";

  /** Replace {name} placeholders; unknown placeholders stay untouched. */
  function fill(s, vars) {
    return String(s).replace(/\{(\w+)\}/g, function (m, k) {
      return vars && Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m;
    });
  }

  /** bbox in PDF points [x0, top, x1, bottom] -> CSS pixel box for an image shown pageW points wide as shownW px. */
  function scaleBox(bbox, pageW, shownW) {
    var k = shownW / pageW;
    return { left: bbox[0] * k, top: bbox[1] * k, width: (bbox[2] - bbox[0]) * k, height: (bbox[3] - bbox[1]) * k };
  }

  /** UI language: explicit ?lang, then saved choice, then browser language (it* -> it, de* -> de, else en). */
  function pickLang(urlLang, saved, navLang) {
    var ok = ["de", "it", "en"];
    if (ok.indexOf(urlLang) >= 0) return urlLang;
    if (ok.indexOf(saved) >= 0) return saved;
    var n = String(navLang || "").toLowerCase();
    return n.indexOf("it") === 0 ? "it" : n.indexOf("de") === 0 ? "de" : "en";
  }

  /** CSS class (colour family) of an answer button, by its i18n key. */
  function optionClass(key) {
    return { "btn.correct": "ok", "btn.yes": "ok", "btn.wrong": "bad", "btn.not_in_document": "none",
             "btn.no": "none", "btn.unsure": "unsure" }[key] || "none";
  }

  /** "1  Richtig" style label: shortcut digit (1-based) and text. */
  function buttonLabel(i, text) { return (i + 1) + "  " + text; }

  /** Progress numbers for the header, never beyond the totals. */
  function progressNumbers(p) {
    var total = p.questions_total || 0, docs = p.docs_total || 0;
    return { n: Math.min(p.questions_done + 1, total), total: total,
             d: Math.min(p.docs_done + 1, docs), docs: docs };
  }

  /** True when less than 400 ms passed since a question appeared (guards against key-repeat answers). */
  function tooSoon(shownAt, now) { return shownAt > 0 && now - shownAt < 400; }

  /** Should this (repeated) keydown be swallowed? Typing keeps native repeat, except a held Enter that confirms the correction. */
  function blockRepeat(k) {
    if (!k.repeat) return false;
    if (k.typing) return k.key === "Enter" && !!k.correctionOpen;
    return /^[1-9]$/.test(k.key) || k.key === "Enter" || k.key.toLowerCase() === "z";
  }

  return { blockRepeat: blockRepeat, tooSoon: tooSoon, fill: fill, scaleBox: scaleBox, pickLang: pickLang, optionClass: optionClass,
           buttonLabel: buttonLabel, progressNumbers: progressNumbers };
});
