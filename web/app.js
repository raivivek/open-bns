/* BNS 2023 site: citation jump, full-text search, typeahead, paragraph link popover. No dependencies. */
(function () {
  "use strict";

  var LONG_SUFFIX = " of the Bharatiya Nyaya Sanhita, 2023";
  var IDX = null;
  var idxPromise = null;

  // ------------------------------------------------------------------ index

  function norm(s) {
    // Length-preserving normalisation so match offsets map back onto the original text.
    return s.toLowerCase().replace(/[\u2018\u2019\u02bc]/g, "'").replace(/[\u201c\u201d]/g, '"').replace(/[\u2013\u2014]/g, "-");
  }

  function prepare(raw) {
    var secs = raw.s.map(function (r, i) {
      return { num: r[0], heading: r[1], ch: r[2], i: i, hl: norm(r[1]), nodes: [] };
    });
    var ids = new Map();
    var lower = new Map();
    secs.forEach(function (s) {
      ids.set(s.num, { id: s.num, sec: s, cite: "Section " + s.num, text: "", depth: 0 });
    });
    raw.n.forEach(function (r) {
      var s = secs[r[1]];
      var n = { id: r[0], sec: s, cite: r[2], text: r[3], tl: norm(r[3]), depth: r[4] };
      s.nodes.push(n);
      ids.set(n.id, n);
    });
    ids.forEach(function (_, k) { lower.set(k.toLowerCase(), k); });
    IDX = { secs: secs, ids: ids, lower: lower };
    return IDX;
  }

  function loadIndex() {
    if (!idxPromise) {
      idxPromise = fetch("/search-index.json")
        .then(function (r) {
          if (!r.ok) throw new Error("search index: HTTP " + r.status);
          return r.json();
        })
        .then(prepare)
        .catch(function (e) { idxPromise = null; throw e; });
    }
    return idxPromise;
  }

  // ------------------------------------------------------------------ citations

  var ACT_RE = "(?:the\\s+)?(?:bns|bharatiya\\s+nyaya\\s+sanhita(?:,?\\s*2023)?)";

  var ORDINAL = { first: 1, second: 2, third: 3, fourth: 4, fifth: 5, sixth: 6, seventh: 7, eighth: 8, ninth: 9, tenth: 10 };
  // "Explanation 1 to", "the second proviso to", "Illustration (a) to", "Exception 4 of" …
  var QUAL_RE = /^(?:the\s+)?(?:(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+)?(explanation|exception|illustration|proviso)(?:\s+(\d+|\(\s*[a-z0-9]+\s*\)))?\s*(?:to|of|under)\s+(?:the\s+)?/i;

  function qualifierId(ord, word, num) {
    word = word.toLowerCase();
    num = num ? num.replace(/[()\s]/g, "").toLowerCase() : "";
    if (word === "proviso") return "proviso-" + (ORDINAL[(ord || "").toLowerCase()] || num || 1);
    if (word === "illustration") return num ? "illus-" + num : "illus";
    var tag = word === "explanation" ? "expl" : "exc";
    return num ? tag + "-" + num : tag;
  }

  function parseCite(q) {
    var s = q.trim().replace(/\s+/g, " ");
    s = s.replace(new RegExp("^" + ACT_RE + "[\\s,:]*", "i"), "");
    var quals = [];
    var m;
    while ((m = QUAL_RE.exec(s))) {
      quals.unshift(qualifierId(m[1], m[2], m[3]));
      s = s.slice(m[0].length);
    }
    s = s.replace(/^(?:§+|sections?|secs?|ss?)\.?\s*(?=\d)/i, "");
    s = s.replace(new RegExp("[\\s,]*(?:of\\s+)?" + ACT_RE + "\\.?$", "i"), "");
    m = /^(\d{1,3})\s*((?:\(\s*[0-9a-z]{1,6}\s*\)\s*)*)$/i.exec(s);
    if (!m) return null;
    var labels = (m[2].match(/\(\s*[0-9a-z]{1,6}\s*\)/gi) || []).map(function (x) {
      return "(" + x.slice(1, -1).trim() + ")";
    });
    return { num: String(parseInt(m[1], 10)), labels: labels, suffix: quals.map(function (x) { return "-" + x; }).join("") };
  }

  function lookup(idx, id) {
    if (idx.ids.has(id)) return id;
    var k = idx.lower.get(id.toLowerCase());
    return k || null;
  }

  // Resolve a citation query to the exact provision, or its nearest existing ancestor.
  function resolveCite(idx, q) {
    var direct = lookup(idx, q.trim());
    if (direct) {
      var dn = idx.ids.get(direct);
      return { id: direct, node: dn, exact: true };
    }
    var p = parseCite(q);
    if (!p || !idx.ids.has(p.num)) return null;
    var base = p.num + p.labels.join("");
    if (p.suffix) {
      var hit = lookup(idx, base + p.suffix);
      if (!hit) {
        // Illustrations may sit under an Explanation (e.g. 2(8)-expl-1-illus-a):
        // accept a unique descendant id with the same tail.
        var pre = (base + "-").toLowerCase();
        var tail = p.suffix.toLowerCase();
        var found = [];
        idx.lower.forEach(function (orig, low) {
          if (low.indexOf(pre) === 0 && low.slice(-tail.length) === tail) found.push(orig);
        });
        if (found.length === 1) hit = found[0];
      }
      if (hit) return { id: hit, node: idx.ids.get(hit), exact: true };
    }
    var labels = p.labels.slice();
    var want = base + p.suffix;
    while (labels.length) {
      var h = lookup(idx, p.num + labels.join(""));
      if (h) return { id: h, node: idx.ids.get(h), exact: !p.suffix && h.toLowerCase() === want.toLowerCase() };
      labels.pop();
    }
    return { id: p.num, node: idx.ids.get(p.num), exact: p.labels.length === 0 && !p.suffix };
  }

  function urlFor(id, num) {
    return "/section-" + num + "/" + (id === num ? "" : "#p-" + id);
  }

  // ------------------------------------------------------------------ full text

  function parseQuery(q) {
    var terms = [];
    var re = /"([^"]+)"|(\S+)/g;
    var m;
    var s = norm(q);
    while ((m = re.exec(s))) {
      var t = (m[1] !== undefined ? m[1] : m[2].replace(/^[^\w(§]+|[^\w)]+$/g, "")).trim();
      if (t && terms.indexOf(t) < 0) terms.push(t);
    }
    return terms;
  }

  function search(idx, q, limit) {
    var terms = parseQuery(q);
    if (!terms.length) return { terms: terms, results: [], total: 0 };
    var T = terms.length;
    var out = [];
    idx.secs.forEach(function (s) {
      var covered = terms.map(function (t) { return s.hl.indexOf(t) >= 0; });
      var hHits = covered.filter(Boolean).length;
      var best = null, bestScore = -1, full = 0;
      for (var i = 0; i < s.nodes.length; i++) {
        var n = s.nodes[i];
        if (!n.tl) continue;
        var c = 0;
        for (var j = 0; j < T; j++) {
          if (n.tl.indexOf(terms[j]) >= 0) { c++; covered[j] = true; }
        }
        if (!c) continue;
        if (c === T) full++;
        var score = c * 100 + n.depth;
        if (score > bestScore) { best = n; bestScore = score; }
      }
      if (!covered.every(Boolean)) return;
      var bestFull = best && bestScore >= T * 100;
      var tier = hHits === T ? 2 : bestFull ? 1 : 0;
      // Heading matches link to the section itself; otherwise to the deepest best-matching paragraph.
      var target = hHits === T ? null : best;
      out.push({ sec: s, node: best, target: target, tier: tier, hHits: hHits, full: full });
    });
    out.sort(function (a, b) {
      return b.tier - a.tier || b.hHits - a.hHits || b.full - a.full || a.sec.i - b.sec.i;
    });
    return { terms: terms, results: out.slice(0, limit || 50), total: out.length };
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function ranges(text, terms) {
    var t = norm(text), r = [];
    terms.forEach(function (term) {
      var i = 0;
      while ((i = t.indexOf(term, i)) >= 0) { r.push([i, i + term.length]); i += term.length; }
    });
    r.sort(function (a, b) { return a[0] - b[0] || b[1] - a[1]; });
    var merged = [];
    r.forEach(function (x) {
      var last = merged[merged.length - 1];
      if (last && x[0] <= last[1]) last[1] = Math.max(last[1], x[1]);
      else merged.push(x.slice());
    });
    return merged;
  }

  function highlight(text, terms, from, to) {
    from = from || 0;
    to = to === undefined ? text.length : to;
    var out = "", pos = from;
    ranges(text, terms).forEach(function (x) {
      var s = Math.max(x[0], from), e = Math.min(x[1], to);
      if (e <= s || s < pos) return;
      out += escapeHtml(text.slice(pos, s)) + "<mark>" + escapeHtml(text.slice(s, e)) + "</mark>";
      pos = e;
    });
    return out + escapeHtml(text.slice(pos, to));
  }

  function snippet(text, terms, width) {
    width = width || 220;
    if (!text) return "";
    var r = ranges(text, terms);
    var start = 0;
    if (r.length && r[0][0] > 60) {
      start = text.lastIndexOf(" ", r[0][0] - 50);
      start = start < 0 ? 0 : start + 1;
    }
    var end = Math.min(text.length, start + width);
    if (end < text.length) {
      var sp = text.lastIndexOf(" ", end);
      if (sp > start + 40) end = sp;
    }
    return (start > 0 ? "… " : "") + highlight(text, terms, start, end) + (end < text.length ? " …" : "");
  }

  function resultView(r, terms) {
    var s = r.sec;
    var id = r.target ? r.target.id : s.num;
    return {
      href: urlFor(id, s.num),
      cite: r.target ? r.target.cite : "Section " + s.num,
      headingHtml: "Section " + escapeHtml(s.num) + ". " + highlight(s.heading, terms),
      snippetHtml: r.node ? snippet(r.node.text, terms) : ""
    };
  }

  // ------------------------------------------------------------------ header typeahead

  function setupTypeahead() {
    var input = document.getElementById("hq");
    var list = document.getElementById("hq-list");
    if (!input || !list) return;
    var form = input.form;
    var items = [], active = -1, timer = 0, seq = 0;

    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", "hq-list");

    function close() {
      list.hidden = true;
      list.innerHTML = "";
      items = [];
      active = -1;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    function setActive(i) {
      active = i;
      Array.prototype.forEach.call(list.children, function (li, k) {
        li.setAttribute("aria-selected", k === i ? "true" : "false");
      });
      if (i >= 0) {
        input.setAttribute("aria-activedescendant", "hq-opt-" + i);
        list.children[i].scrollIntoView({ block: "nearest" });
      } else input.removeAttribute("aria-activedescendant");
    }

    function render(q) {
      if (!IDX || !q.trim()) return close();
      var opts = [];
      var c = resolveCite(IDX, q);
      if (c) {
        opts.push({
          href: urlFor(c.id, c.node.sec.num),
          html: '<span class="tc">Go to ' + escapeHtml(c.node.cite) + "</span> " +
            '<span class="th">' + escapeHtml(c.node.sec.heading) + "</span>" +
            (c.exact ? "" : '<span class="tx">nearest existing provision</span>')
        });
      }
      var res = search(IDX, q, 8);
      res.results.slice(0, c ? 7 : 8).forEach(function (r) {
        var v = resultView(r, res.terms);
        opts.push({
          href: v.href,
          html: '<span class="tc">' + escapeHtml(v.cite) + '</span> <span class="th">' + escapeHtml(r.sec.heading) +
            '</span><span class="tx">' + v.snippetHtml + "</span>"
        });
      });
      if (res.total > opts.length) {
        opts.push({ href: "/search/?q=" + encodeURIComponent(q), html: '<span class="th">All ' + res.total + " results…</span>" });
      }
      if (!opts.length) return close();
      items = opts;
      list.innerHTML = opts.map(function (o, i) {
        return '<li role="option" id="hq-opt-' + i + '" aria-selected="false" data-href="' + escapeHtml(o.href) + '">' + o.html + "</li>";
      }).join("");
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      setActive(c ? 0 : -1);
    }

    function update() {
      var q = input.value, my = ++seq;
      loadIndex().then(function () { if (my === seq) render(q); }, function () {});
    }

    function go(href) { window.location.href = href; }

    input.addEventListener("focus", function () { loadIndex().catch(function () {}); }, { once: true });
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(update, 70);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (list.hidden) { update(); e.preventDefault(); return; }
        e.preventDefault();
        var n = items.length;
        if (!n) return;
        setActive(e.key === "ArrowDown" ? (active + 1) % n : (active <= 0 ? n - 1 : active - 1));
      } else if (e.key === "Escape") {
        if (!list.hidden) { e.preventDefault(); close(); }
      } else if (e.key === "Enter") {
        if (active >= 0 && items[active]) { e.preventDefault(); go(items[active].href); }
      }
    });
    form.addEventListener("submit", function (e) {
      var q = input.value;
      if (!q.trim()) { e.preventDefault(); return; }
      e.preventDefault();
      loadIndex().then(function (idx) {
        var c = resolveCite(idx, q);
        go(c ? urlFor(c.id, c.node.sec.num) : "/search/?q=" + encodeURIComponent(q));
      }, function () { form.submit(); });
    });
    list.addEventListener("mousedown", function (e) { e.preventDefault(); });
    list.addEventListener("click", function (e) {
      var li = e.target.closest("li[data-href]");
      if (li) go(li.getAttribute("data-href"));
    });
    input.addEventListener("blur", function () { setTimeout(close, 120); });
  }

  // ------------------------------------------------------------------ search page

  function setupSearchPage() {
    var input = document.getElementById("sq");
    var status = document.getElementById("sstatus");
    var list = document.getElementById("sresults");
    if (!input || !status || !list) return;
    var q = new URLSearchParams(window.location.search).get("q") || "";
    input.value = q;
    if (!q.trim()) { input.focus(); loadIndex().catch(function () {}); return; }
    document.title = "“" + q + "” — Search | BNS 2023";
    status.textContent = "Searching…";
    loadIndex().then(function (idx) {
      var c = resolveCite(idx, q);
      if (c) { window.location.replace(urlFor(c.id, c.node.sec.num)); return; }
      var res = search(idx, q, 50);
      var p = parseCite(q);
      var lead = p && !idx.ids.has(p.num) ? "There is no section " + p.num + " in the Sanhita (it has sections 1–" + idx.secs.length + "). " : "";
      status.textContent = lead + (res.total
        ? res.total + (res.total === 1 ? " section matches" : " sections match") + " “" + q + "”" + (res.total > 50 ? "; showing the first 50." : ".")
        : "No matches for “" + q + "”.");
      list.innerHTML = res.results.map(function (r) {
        var v = resultView(r, res.terms);
        return '<li><a href="' + escapeHtml(v.href) + '">' + v.headingHtml + '</a><span class="rc">' + escapeHtml(v.cite) +
          (r.full > 1 ? " · " + r.full + " matching paragraphs" : "") + "</span>" +
          (v.snippetHtml ? '<p class="rs">' + v.snippetHtml + "</p>" : "") + "</li>";
      }).join("");
    }, function (e) {
      status.textContent = "Could not load the search index (" + e.message + ").";
    });
  }

  // ------------------------------------------------------------------ paragraph link popover

  var pop = null, popFor = null;

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      if (ok) { resolve(); } else { reject(new Error("copy failed")); }
    });
  }

  function closePop(restore) {
    if (!pop) return;
    pop.remove();
    pop = null;
    if (popFor) {
      popFor.setAttribute("aria-expanded", "false");
      if (restore) popFor.focus();
    }
    popFor = null;
  }

  function openPop(a) {
    closePop(false);
    var cite = a.getAttribute("data-c") || "";
    var long = a.getAttribute("data-l");
    var page = a.getAttribute("data-p");
    var link = window.location.origin + a.getAttribute("href");
    var shortC = cite + ", BNS";
    var longC = long ? long + LONG_SUFFIX : null;
    pop = document.createElement("div");
    pop.className = "pop";
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", cite);
    pop.innerHTML =
      '<p class="pc">' + escapeHtml(shortC) + "</p>" +
      (longC ? '<p class="plong">' + escapeHtml(longC) + "</p>" : "") +
      '<div class="pb"><button type="button" data-copy="link">Copy link</button>' +
      '<button type="button" data-copy="short">Copy citation</button>' +
      (longC ? '<button type="button" data-copy="long">Copy long citation</button>' : "") + "</div>" +
      (page ? '<a class="pg" href="/source/bns-2023-gazette.pdf#page=' + escapeHtml(page) + '">Gazette p. ' + escapeHtml(page) + "</a>" : "");
    var values = { link: link, short: shortC, long: longC };
    pop.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-copy]");
      if (!b) return;
      var label = b.textContent;
      copyText(values[b.getAttribute("data-copy")]).then(function () {
        b.textContent = "Copied";
      }, function () {
        b.textContent = "Copy failed";
      }).then(function () {
        setTimeout(function () { b.textContent = label; }, 1400);
      });
    });
    pop.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); closePop(true); }
    });
    document.body.appendChild(pop);
    var r = a.getBoundingClientRect();
    var w = pop.offsetWidth;
    var left = Math.max(8, Math.min(r.left + window.scrollX, window.scrollX + document.documentElement.clientWidth - w - 8));
    pop.style.left = left + "px";
    pop.style.top = r.bottom + window.scrollY + 4 + "px";
    popFor = a;
    a.setAttribute("aria-expanded", "true");
    pop.querySelector("button").focus();
  }

  function setupPilcrows() {
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a.pil");
      if (a) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
        e.preventDefault();
        if (popFor === a) { closePop(true); return; }
        openPop(a);
        return;
      }
      if (pop && !pop.contains(e.target)) closePop(false);
    });
    document.querySelectorAll("a.pil").forEach(function (a) {
      a.setAttribute("aria-haspopup", "dialog");
      a.setAttribute("aria-expanded", "false");
    });
  }

  // ------------------------------------------------------------------ contents toggle

  function setupToc() {
    var btn = document.querySelector(".toc-btn");
    var toc = document.getElementById("toc");
    if (!toc) return;
    var cur = toc.querySelector("a[aria-current]");
    if (cur && toc.scrollHeight > toc.clientHeight) {
      toc.scrollTop = cur.offsetTop - toc.offsetTop - toc.clientHeight / 3;
    }
    if (!btn) return;
    btn.hidden = false;
    function set(open) {
      document.body.classList.toggle("toc-open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }
    btn.addEventListener("click", function () {
      var open = !document.body.classList.contains("toc-open");
      set(open);
      if (open) {
        var a = toc.querySelector("a[aria-current]") || toc.querySelector("a");
        if (a) a.focus();
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && document.body.classList.contains("toc-open")) { set(false); btn.focus(); }
    });
    toc.addEventListener("click", function (e) {
      if (e.target.closest("a")) set(false);
    });
    document.addEventListener("click", function (e) {
      if (document.body.classList.contains("toc-open") && !toc.contains(e.target) && !btn.contains(e.target)) set(false);
    });
  }

  // "Expand all" / "Collapse all" for the sidebar tree and the home-page contents.
  function setupToggles() {
    document.querySelectorAll(".tgl").forEach(function (bar) {
      var scope = bar.closest(".toc, .htoc");
      if (!scope) return;
      bar.hidden = false;
      bar.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-tgl]");
        if (!b) return;
        var open = b.getAttribute("data-tgl") === "open";
        scope.querySelectorAll("details").forEach(function (d) { d.open = open; });
      });
    });
  }

  function init() {
    setupTypeahead();
    setupPilcrows();
    setupToc();
    setupToggles();
    if (document.body.getAttribute("data-page") === "search") setupSearchPage();
  }

  // Exposed for testing in Node (no DOM): require("./app.js") returns the pure helpers.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { prepare: prepare, parseCite: parseCite, resolveCite: resolveCite, search: search, urlFor: urlFor, snippet: snippet };
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
