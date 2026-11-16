// Panel del servidor: pide /api/stats cada 2 s y actualiza indicadores, gráficas, procesos y servicios.
(function () {
  "use strict";
  var EVERY = 2000, MAXH = 150;
  var H = [], last = null, sortBy = "cpu", fails = 0, timer = null, lastOk = 0;
  try { var s0 = localStorage.getItem("panel-sort"); if (s0 === "mem" || s0 === "cpu") sortBy = s0; } catch (e) {}
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function set(node, v) { if (node && node.textContent !== v) node.textContent = v; }

  // ---------- formato ----------
  function num(v, d) { return v.toLocaleString("es-ES", {minimumFractionDigits: d, maximumFractionDigits: d}); }
  function bytes(b) {
    var u = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return num(b, i === 0 ? 0 : b < 10 ? 2 : b < 100 ? 1 : 0) + " " + u[i];
  }
  function rate(b) { return bytes(b) + "/s"; }
  function dur(s) {
    s = Math.max(0, Math.floor(s));
    var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    return d ? d + " d " + h + " h" : h ? h + " h " + m + " min" : m ? m + " min" : s + " s";
  }
  function lvl(v, warn, bad) { return v >= bad ? "bad" : v >= warn ? "warn" : ""; }

  // ---------- gráficas (SVG) ----------
  var NS = "http://www.w3.org/2000/svg";
  function path(vals, w, h, max, pad) {
    var n = vals.length; if (n < 2) return null;
    var step = w / (MAXH - 1), x0 = w - (n - 1) * step, d = "", top = pad || 3;
    for (var i = 0; i < n; i++) {
      var v = vals[i] == null ? 0 : vals[i];
      var y = h - (Math.min(v, max) / max) * (h - top) ;
      d += (i ? "L" : "M") + (x0 + i * step).toFixed(1) + " " + y.toFixed(1);
    }
    return {line: d, area: d + "L" + w + " " + h + "L" + x0.toFixed(1) + " " + h + "Z"};
  }
  function series(svg, cls, vals, w, h, max) {
    var g = svg.querySelector("g." + cls);
    if (!g) {
      g = document.createElementNS(NS, "g"); g.setAttribute("class", cls);
      var a = document.createElementNS(NS, "path"); a.setAttribute("class", "ar");
      var l = document.createElementNS(NS, "path"); l.setAttribute("class", "ln");
      g.appendChild(a); g.appendChild(l); svg.appendChild(g);
    }
    var p = path(vals, w, h, max);
    g.children[0].setAttribute("d", p ? p.area : ""); g.children[1].setAttribute("d", p ? p.line : "");
  }
  function col(k) { return H.map(function (x) { return x[k]; }); }
  function niceMax(v) {
    var base = 1024 * 10; // mínimo 10 KB/s para que el ruido no llene la gráfica
    if (v <= base) return base;
    var p = Math.pow(2, Math.ceil(Math.log(v) / Math.LN2));
    return v <= p * 0.75 ? p * 0.75 : p;
  }
  function drawCharts() {
    var q = function (n) { return document.querySelector('[data-spark="' + n + '"]'); };
    series(q("cpu"), "c1", col("cpu"), 300, 64, 100);
    series(q("mem"), "c2", col("mem"), 300, 64, 100);
    var temps = col("temp").filter(function (v) { return v != null; });
    if (temps.length) series(q("temp"), "c3", col("temp").map(function (v) { return v == null ? 0 : Math.max(v - 20, 0); }), 300, 64, 80);
    var rx = col("rx"), tx = col("tx"), mx = niceMax(Math.max.apply(null, rx.concat(tx).concat([0])));
    series(q("net"), "c2", rx, 300, 64, mx); series(q("net"), "c4", tx, 300, 64, mx);
    var big = $("net-chart");
    if (!big.querySelector(".gl")) for (var i = 1; i < 4; i++) {
      var ln = document.createElementNS(NS, "line"); ln.setAttribute("class", "gl");
      ln.setAttribute("x1", 0); ln.setAttribute("x2", 900); ln.setAttribute("y1", 55 * i); ln.setAttribute("y2", 55 * i); big.appendChild(ln);
    }
    series(big, "c2", rx, 900, 220, mx); series(big, "c4", tx, 900, 220, mx);
    set($("net-max"), rate(mx));
    if (H.length > 1) set($("net-range"), "últimos " + dur(H[H.length - 1].t - H[0].t));
  }

  // ---------- pintado ----------
  function bar(pct, warn, bad) {
    var b = el("div", "bar " + lvl(pct, warn, bad)), i = el("i"); i.style.width = Math.max(0, Math.min(100, pct)) + "%"; b.appendChild(i); return b;
  }
  function keyed(parent, key, make) {   // reutiliza nodos para que las barras se animen en vez de recrearse
    var n = parent.querySelector('[data-key="' + key.replace(/"/g, "") + '"]');
    if (!n) { n = make(); n.setAttribute("data-key", key.replace(/"/g, "")); parent.appendChild(n); }
    return n;
  }
  function row(parent, key, name, right, pct, warn, bad) {
    var n = keyed(parent, key, function () {
      var r = el("div", "row"), t = el("div", "t"); t.appendChild(el("span")); t.appendChild(el("span")); r.appendChild(t); r.appendChild(bar(0, warn, bad)); return r;
    });
    set(n.querySelector(".t span"), name); set(n.querySelector(".t span:last-child"), right);
    var b = n.querySelector(".bar"); b.className = "bar " + lvl(pct, warn, bad); b.firstChild.style.width = Math.max(0, Math.min(100, pct)) + "%";
  }
  function kpi(id, value, detail, cls) {
    var k = $(id); set(k.querySelector("[data-v]"), value); set(k.querySelector("[data-d]"), detail); k.className = "card kpi " + (cls || "");
  }
  function chip(label, value, cls) { var c = el("span", "chip " + (cls || ""), label + " "); c.appendChild(el("b", "", value)); return c; }

  function paint(d) {
    if (!d || !d.cpu) return;
    var h = d.host, m = d.mem;
    set($("h-name"), h.name || "Servidor");
    set($("h-sub"), (h.cpu_model || "CPU") + " · " + h.cores + " núcleos · Linux " + h.kernel);
    var chips = $("h-chips"); chips.textContent = "";
    chips.appendChild(chip("Encendido", dur(h.uptime)));
    if (h.load.length) chips.appendChild(chip("Carga", h.load.map(function (x) { return num(x, 2); }).join(" · "), lvl(h.load[0] / h.cores * 100, 100, 200)));
    if (d.battery) chips.appendChild(chip(d.battery.ac === false ? "Batería (sin corriente)" : "Batería", d.battery.pct + " %", d.battery.ac === false ? (d.battery.pct < 25 ? "bad" : "warn") : ""));

    kpi("k-cpu", num(d.cpu.pct, 0), "E/S en espera " + num(d.cpu.iowait, 1) + " % · " + h.procs + " procesos", lvl(d.cpu.pct, 75, 92));
    kpi("k-mem", num(m.pct, 0), bytes(m.used) + " de " + bytes(m.total), lvl(m.pct, 80, 92));
    var t = d.temp.main;
    kpi("k-temp", t == null ? "—" : num(t, 0), t == null ? "Sin sensor de temperatura" : (t >= 85 ? "Muy alta" : t >= 70 ? "Alta" : "Normal") + " · " + d.temp.sensors.length + " sensores", t == null ? "" : lvl(t, 70, 85));
    var kn = $("k-net"); set(kn.querySelector("[data-rx]"), rate(d.net.rx)); set(kn.querySelector("[data-tx]"), rate(d.net.tx));
    set(kn.querySelector("[data-d]"), "Disco: ↓ " + rate(d.disk.read) + " · ↑ " + rate(d.disk.write));

    var cores = $("cores");
    d.cpu.cores.forEach(function (p, i) {
      var n = keyed(cores, "c" + i, function () { var c = el("div", "core"), tt = el("div", "t"); tt.appendChild(el("span", "", "Núcleo " + (i + 1))); tt.appendChild(el("b")); c.appendChild(tt); c.appendChild(bar(0, 75, 92)); return c; });
      set(n.querySelector("b"), num(p, 0) + " %");
      var b = n.querySelector(".bar"); b.className = "bar " + lvl(p, 75, 92); b.firstChild.style.width = p + "%";
    });
    var kv = $("cpu-kv"); kv.textContent = "";
    [["Carga 1 / 5 / 15 min", h.load.map(function (x) { return num(x, 2); }).join(" / ") || "—"], ["Procesos · hilos", h.procs + " · " + h.threads], ["Tiempo encendido", dur(h.uptime)]]
      .forEach(function (p) { var x = el("div", "", p[0]); x.appendChild(el("b", "", p[1])); kv.appendChild(x); });

    var bars = $("bars");
    row(bars, "ram", "Memoria RAM", bytes(m.used) + " / " + bytes(m.total) + " · caché " + bytes(m.cached), m.pct, 80, 92);
    if (m.swap_total) row(bars, "swap", "Intercambio (swap)", bytes(m.swap_used) + " / " + bytes(m.swap_total), m.swap_used / m.swap_total * 100, 50, 80);
    d.disk.mounts.forEach(function (k) { row(bars, "d-" + k.name, k.name, bytes(k.used) + " / " + bytes(k.total) + " · libre " + bytes(k.free), k.pct, 80, 92); });

    var tb = $("ifaces").tBodies[0]; tb.textContent = "";
    d.net.ifaces.forEach(function (f) {
      var tr = el("tr"); tr.appendChild(el("td", "", f.name));
      [rate(f.rx), rate(f.tx), bytes(f.rx_total), bytes(f.tx_total)].forEach(function (v) { tr.appendChild(el("td", "num", v)); });
      tb.appendChild(tr);
    });
    paintProcs(d);

    var sv = $("svcs");
    if (d.services && d.services.length) {
      sv.textContent = "";
      d.services.forEach(function (s) {
        var li = el("li", s.ok ? "" : "down"); li.appendChild(el("span", "dot"));
        var n = el("span", "n");
        if (s.link && /^https?:\/\//.test(s.link)) { var a = el("a", "", s.name); a.href = s.link; a.target = "_blank"; a.rel = "noopener noreferrer"; n.appendChild(a); } else n.textContent = s.name;
        li.appendChild(n); li.appendChild(el("span", "ms", s.ok ? s.ms + " ms" : "Caído"));
        var meta = el("div", "meta"); meta.appendChild(el("span", "", (s.ok ? "Funciona" : "Sin respuesta") + " desde hace " + dur(d.t - s.since) + " · " + s.detail));
        var tk = el("span", "ticks"); tk.title = "Últimas comprobaciones"; s.hist.slice(-20).forEach(function (o) { tk.appendChild(el("i", o ? "" : "x")); });
        meta.appendChild(tk); li.appendChild(meta); sv.appendChild(li);
      });
    }
    var se = $("sensors");
    if (d.temp.sensors.length) {
      se.textContent = "";
      d.temp.sensors.forEach(function (s) { var li = el("li"); li.appendChild(el("span", "", s.name === s.chip ? s.chip : s.name + " (" + s.chip + ")")); li.appendChild(el("b", lvl(s.c, 70, 85), num(s.c, 1) + " °C")); se.appendChild(li); });
    }
    set($("foot"), "Actualizado a las " + new Date(d.t * 1000).toLocaleTimeString("es-ES") + " · cada " + (EVERY / 1000) + " s");
  }
  function paintProcs(d) {
    var tb = $("procs").tBodies[0]; tb.textContent = "";
    (d.procs[sortBy] || []).forEach(function (p) {
      var tr = el("tr"), td = el("td", "p"); td.appendChild(el("b", "", p.name)); var sm = el("small", "", p.cmd); sm.title = p.cmd; td.appendChild(sm); tr.appendChild(td);
      tr.appendChild(el("td", "u", p.user));
      var c = el("td", "num"); c.appendChild(el("span", p.cpu >= 80 ? "vhot" : p.cpu >= 40 ? "hot" : "", num(p.cpu, 1) + " %")); tr.appendChild(c);
      tr.appendChild(el("td", "num", bytes(p.mem)));
      tb.appendChild(tr);
    });
    set($("procs-foot"), "Los " + (d.procs[sortBy] || []).length + " procesos que más " + (sortBy === "cpu" ? "CPU" : "memoria") + " usan. El 100 % de CPU equivale a un núcleo completo.");
  }
  document.querySelectorAll("[data-sort]").forEach(function (b) {
    b.classList.toggle("on", b.getAttribute("data-sort") === sortBy);
    b.addEventListener("click", function () {
      sortBy = b.getAttribute("data-sort"); try { localStorage.setItem("panel-sort", sortBy); } catch (e) {}
      document.querySelectorAll("[data-sort]").forEach(function (x) { x.classList.toggle("on", x === b); });
      if (last) paintProcs(last);
    });
  });

  // ---------- conexión ----------
  function live(cls, text) { var l = $("live"); l.className = "live " + cls; set(l.querySelector("b"), text); }
  function tick(full) {
    fetch("/api/stats" + (full ? "?h=1" : ""), {cache: "no-store", credentials: "same-origin"}).then(function (r) {
      if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
      if (!r.ok) throw new Error("http");
      return r.json();
    }).then(function (d) {
      fails = 0; lastOk = Date.now();
      if (!d.cpu) { live("", "Tomando la primera muestra…"); return; }
      if (d.history) H = d.history;
      else if (!H.length || d.t > H[H.length - 1].t) H.push({t: d.t, cpu: d.cpu.pct, mem: d.mem.pct, temp: d.temp.main, rx: d.net.rx, tx: d.net.tx});
      while (H.length > MAXH) H.shift();
      last = d; paint(d); drawCharts(); live("on", "En vivo");
    }).catch(function () { if (++fails >= 2) live("off", "Sin conexión"); });
  }
  function start() { if (timer) return; tick(Date.now() - lastOk > 10000); timer = setInterval(function () { tick(false); }, EVERY); }
  function stop() { clearInterval(timer); timer = null; live("paused", "En pausa"); }
  document.addEventListener("visibilitychange", function () { document.hidden ? stop() : start(); });
  start();
})();
