// SaiperrNexo: una sola página con las secciones del panel. Cada sección es una función de V que pinta en #view.
(function () {
  "use strict";
  var CSRF = document.querySelector('meta[name="csrf"]').content;
  var B = null, timers = [], V = {}, fails = 0;
  var LEVEL = {lector: 1, operador: 2, admin: 3}, ROLE = {lector: "Lector", operador: "Operador", admin: "Administrador"};
  function $(id) { return document.getElementById(id); }

  // ---------- utilidades ----------
  function add(e, kids) {
    kids.forEach(function (k) {
      if (Array.isArray(k)) add(e, k);
      else if (k != null && k !== false) e.appendChild(k.nodeType ? k : document.createTextNode(String(k)));
    });
    return e;
  }
  function mk(e, attrs, kids) {
    for (var k in attrs || {}) {
      var v = attrs[k];
      if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), v);
      else if (k === "class") e.setAttribute("class", v);
      else if (k === "value" && "value" in e) e.value = v;
      else if (v === true) e.setAttribute(k, "");
      else if (v !== false && v != null) e.setAttribute(k, v);
    }
    return add(e, kids);
  }
  function h(tag, attrs) { return mk(document.createElement(tag), attrs, [].slice.call(arguments, 2)); }
  function s(tag, attrs) { return mk(document.createElementNS("http://www.w3.org/2000/svg", tag), attrs, [].slice.call(arguments, 2)); }
  function can(role) { return LEVEL[B.user.role] >= LEVEL[role]; }
  function live(on) { var l = $("live"); l.className = "live " + (on ? "on" : "off"); l.querySelector("b").textContent = on ? "Conectado" : "Sin conexión"; }
  function api(method, path, body) {
    var opt = {method: method, credentials: "same-origin", cache: "no-store", headers: {"X-CSRF-Token": CSRF}};
    if (body instanceof FormData) opt.body = body;
    else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
    return fetch(path, opt).then(function (r) {
      fails = 0; live(true);
      if (r.status === 401) { location.href = "/login"; throw new Error("Sesión caducada"); }
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.detail || "Error " + r.status);
        return d;
      });
    }, function () { if (++fails >= 2) live(false); throw new Error("Sin conexión con el panel"); });
  }
  var toastT;
  function toast(msg, err) {
    var t = $("toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { t.hidden = true; }, err ? 6000 : 3000);
  }
  function fail(e) { toast(e.message, true); }
  function every(ms, fn) { fn(); timers.push(setInterval(function () { if (!document.hidden) fn(); }, ms)); }
  function quiet(p) { return p.catch(function () {}); }     // refrescos periódicos: el aviso ya lo da el indicador de conexión

  function num(v, d) { return Number(v).toLocaleString("es-ES", {minimumFractionDigits: d, maximumFractionDigits: d}); }
  function bytes(b) {
    var u = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return num(b, i === 0 ? 0 : b < 10 ? 2 : b < 100 ? 1 : 0) + " " + u[i];
  }
  function rate(b) { return bytes(b) + "/s"; }
  function dur(x) {
    x = Math.max(0, Math.floor(x));
    var d = Math.floor(x / 86400), hh = Math.floor(x % 86400 / 3600), m = Math.floor(x % 3600 / 60);
    return d ? d + " d " + hh + " h" : hh ? hh + " h " + m + " min" : m ? m + " min" : x + " s";
  }
  function when(iso) { var m = /^(\d{4})-(\d\d)-(\d\d)[T ](\d\d:\d\d)/.exec(iso || ""); return m ? m[3] + "/" + m[2] + "/" + m[1] + " " + m[4] : "—"; }
  function day(ts) { var d = new Date(ts * 1000), p = function (n) { return (n < 10 ? "0" : "") + n; }; return p(d.getDate()) + "/" + p(d.getMonth() + 1) + "/" + d.getFullYear() + " " + p(d.getHours()) + ":" + p(d.getMinutes()); }
  function lvl(v, warn, bad) { return v >= bad ? "bad" : v >= warn ? "warn" : ""; }

  // ---------- piezas ----------
  var ICON = {
    dashboard: "M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-3H4zM14 7h6V4h-6z", apps: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    docker: "M3 8l9-4 9 4-9 4zM3 8v8l9 4 9-4V8M12 12v8", files: "M3 6h6l2 2h10v11H3z", terminal: "M3 5h18v14H3zM7 10l3 2-3 2M12 15h4",
    net: "M12 3v6M5 21v-5h14v5M12 9v7M5 16h14M3 21h4M10 21h4M17 21h4", users: "M16 20v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M9.5 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M21 20v-1a4 4 0 0 0-3-3.8M15.5 4.2a3.5 3.5 0 0 1 0 6.6",
    autos: "M12 7v5l3 2M21 12a9 9 0 1 1-9-9M16 3h5v5", plugins: "M9 3v4M15 3v4M6 7h12v5a6 6 0 0 1-12 0zM12 18v3",
    settings: "M4 6h10M18 6h2M4 12h2M10 12h10M4 18h8M16 18h4M16 4v4M8 10v4M14 16v4", plugin: "M4 4h16v16H4zM4 9h16",
    restart: "M20 11a8 8 0 1 0-2.3 6.3M20 4v7h-7", stop: "M7 7h10v10H7z", start: "M8 5l11 7-11 7z", pause: "M8 5v14M16 5v14",
    logs: "M5 4h14v16H5zM9 9h6M9 13h6M9 17h3", info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 11v5M12 8h.01",
    edit: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4", trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5", close: "M6 6l12 12M18 6L6 18",
    plus: "M12 5v14M5 12h14", search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14M20 20l-4-4", file: "M6 3h8l4 4v14H6zM14 3v4h4", download: "M12 4v11M7 11l5 5 5-5M5 20h14",
    out: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"
  };
  function icon(k) { return s("svg", {class: "i", viewBox: "0 0 24 24", "aria-hidden": "true"}, s("path", {d: ICON[k]})); }
  function btn(text, fn, cls, ic) { return h("button", {type: "button", class: cls || "sec small", onclick: fn}, ic ? icon(ic) : null, text); }
  function ib(ic, title, fn, cls) { return h("button", {type: "button", class: "ib " + (cls || ""), title: title, "aria-label": title, onclick: fn}, icon(ic)); }
  function badge(text, kind) { return h("span", {class: "badge " + (kind || "")}, text); }
  function card(title) { return h("section", {class: "card"}, title ? h("h2", {}, title) : null, [].slice.call(arguments, 1)); }
  // Tarjeta con tabla a sangre: cabecera con título y acciones, y el contenido pegado a los bordes.
  function panel(title, right) { return h("section", {class: "card flush"}, h("div", {class: "head"}, h("h2", {}, title), right ? h("div", {class: "row"}, right) : null), [].slice.call(arguments, 2)); }
  function table(heads, rows) {
    return h("div", {class: "tbl"}, h("table", {}, h("thead", {}, h("tr", {}, heads.map(function (x) {
      var c = (/^#/.test(x) ? "num " : "") + (/\*$/.test(x) ? "hide-s" : "");
      return h("th", {class: c}, x.replace(/^#|\*$/g, ""));
    }))), h("tbody", {}, rows)));
  }
  function loading() { return h("p", {class: "empty"}, "Cargando…"); }
  function meter(name, right, pct, warn, bad) {
    return h("div", {class: "meter"}, h("div", {class: "t"}, h("span", {}, name), h("span", {}, right)),
      h("div", {class: "bar2 " + lvl(pct, warn, bad)}, h("i", {style: "width:" + Math.max(0, Math.min(100, pct)) + "%"})));
  }
  function modal(title) {
    var body = h("div", {class: "db"}, [].slice.call(arguments, 1));
    var d = h("dialog", {}, h("div", {class: "dh"}, h("h2", {}, title), ib("close", "Cerrar", function () { d.close(); })), body);
    d.addEventListener("close", function () { d.remove(); });
    document.body.appendChild(d); d.showModal();
    return d;
  }
  // Confirmación propia (en lugar de la del navegador). Solo resuelve si se acepta.
  function sure(title, text, okText, danger) {
    return new Promise(function (resolve) {
      var d = modal(title, h("p", {class: "mut"}, text), h("div", {class: "df"}, btn("Cancelar", function () { d.close(); }, "sec"),
        btn(okText || "Aceptar", function () { d.close(); resolve(); }, danger ? "danger solid" : "")));
      d.className = "sm";
    });
  }
  // Formulario en ventana: fields = [{k, label, type, value, options, hint}]; resuelve con los valores al aceptar.
  function ask(title, fields, okText) {
    return new Promise(function (resolve) {
      var inputs = {}, d, form = h("form", {method: "dialog"}, fields.map(function (f) {
        var i;
        if (f.options) i = h("select", {}, f.options.map(function (o) { o = Array.isArray(o) ? o : [o, o]; return h("option", {value: o[0], selected: String(o[0]) === String(f.value)}, o[1]); }));
        else i = h("input", {type: f.type || "text", value: f.value == null ? "" : f.value, placeholder: f.placeholder, autocomplete: f.type === "password" ? "new-password" : "off", required: f.required});
        inputs[f.k] = i;
        return [h("label", {}, f.label), i, f.hint ? h("p", {class: "hint"}, f.hint) : null];
      }), h("div", {class: "df"}, btn("Cancelar", function () { d.close(); }, "sec"), h("button", {}, okText || "Guardar")));
      d = modal(title, form); d.className = "sm";
      form.addEventListener("submit", function () { var out = {}; for (var k in inputs) out[k] = inputs[k].value; resolve(out); });
    });
  }

  // ---------- gráficas ----------
  var MAXH = 150;
  function draw(svg, w, hgt, max, list, lines) {
    svg.textContent = "";
    for (var g = 1; g <= (lines || 0); g++) svg.appendChild(s("line", {class: "gridl", x1: 0, x2: w, y1: hgt * g / (lines + 1), y2: hgt * g / (lines + 1)}));
    list.forEach(function (vals, idx) {
      var n = vals.length; if (n < 2) return;
      var step = w / (MAXH - 1), x0 = w - (n - 1) * step, d = "";
      for (var i = 0; i < n; i++) d += (i ? "L" : "M") + (x0 + i * step).toFixed(1) + " " + (hgt - Math.min(vals[i] || 0, max) / max * (hgt - 3)).toFixed(1);
      svg.appendChild(s("g", {class: idx ? "s2" : ""}, s("path", {class: "ar", d: d + "L" + w + " " + hgt + "L" + x0.toFixed(1) + " " + hgt + "Z"}), s("path", {class: "ln", d: d})));
    });
  }
  function niceMax(v) {
    if (v <= 10240) return 10240;
    var p = Math.pow(2, Math.ceil(Math.log(v) / Math.LN2));
    return v <= p * 0.75 ? p * 0.75 : p;
  }

  // ---------- Dashboard ----------
  V.dashboard = function (root) {
    var H = [], S = B.settings, sortBy = "cpu", lastD = null, K = {};
    function kpi(key, label, unit) {
      var k = K[key] = {v: h("b", {}, "—"), d: h("div", {class: "d"}, "\u00a0"), svg: s("svg", {viewBox: "0 0 300 46", preserveAspectRatio: "none", "aria-hidden": "true"})};
      k.card = h("section", {class: "card kpi"}, h("div", {class: "k"}, label), h("div", {class: "v"}, k.v, h("small", {}, unit)), k.d, k.svg);
      return k.card;
    }
    var rx = h("b", {}, "—"), tx = h("b", {}, "—"), nd = h("div", {class: "d"}, "\u00a0"), nsvg = s("svg", {viewBox: "0 0 300 46", preserveAspectRatio: "none", "aria-hidden": "true"});
    var stDot = h("span", {class: "dot"}), stText = h("b", {}, "Comprobando el estado…"), stRight = h("span", {class: "r"}), status = h("section", {class: "card status"}, stDot, stText, h("span", {class: "sp"}), stRight);
    var svcs = h("ul", {class: "list"}), sum = h("ul", {class: "list"}), cores = h("div", {class: "cores"}), bars = h("div");
    var big = s("svg", {class: "chart", viewBox: "0 0 900 210", preserveAspectRatio: "none", role: "img", "aria-label": "Tráfico de red de los últimos minutos"}), ymax = h("span", {class: "ymax"});
    var procs = h("tbody"), sensors = h("ul", {class: "list"});
    var seg = h("div", {class: "seg"}, ["cpu", "mem"].map(function (k) {
      return h("button", {type: "button", class: k === sortBy ? "on" : "", onclick: function (e) { sortBy = k; seg.querySelectorAll("button").forEach(function (b) { b.className = b === e.target ? "on" : ""; }); if (lastD) paintProcs(lastD); }}, k === "cpu" ? "CPU" : "Memoria");
    }));
    add(root, [status,
      h("div", {class: "grid g4"}, kpi("cpu", "CPU", "%"), kpi("mem", "Memoria", "%"), kpi("temp", "Temperatura", "°C"),
        h("section", {class: "card kpi"}, h("div", {class: "k"}, "Red"), h("div", {class: "v two"}, h("div", {}, h("span", {}, "↓"), rx), h("div", {}, h("span", {}, "↑"), tx)), nd, nsvg)),
      h("div", {class: "grid gl"},
        h("section", {class: "card"}, h("div", {class: "head"}, h("h2", {}, "Tráfico de red"), h("div", {class: "legend"}, h("span", {}, h("i"), "Bajada"), h("span", {class: "t"}, h("i"), "Subida"))), h("div", {class: "chart-wrap"}, big, ymax)),
        card("Resumen", sum)),
      h("div", {class: "grid g2"}, card("Aplicaciones", svcs), card("Recursos", bars, cores)),
      h("div", {class: "grid " + (S.mod_sensors ? "gl" : "")},
        h("section", {class: "card flush"}, h("div", {class: "head"}, h("h2", {}, "Procesos"), seg), h("div", {class: "tbl"}, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Proceso"), h("th", {class: "hide-s"}, "Usuario"), h("th", {class: "num"}, "CPU"), h("th", {class: "num"}, "Memoria"))), procs))),
        S.mod_sensors ? card("Sensores", sensors) : null)
    ]);
    function setK(key, value, detail, cls) { K[key].v.textContent = value; K[key].d.textContent = detail; K[key].card.className = "card kpi " + (cls || ""); }
    function li(name, right, dot) { return h("li", {}, h("span", {class: "n"}, dot ? h("span", {class: "dot " + dot}) : null, name), h("span", {class: "r"}, right)); }
    function paintProcs(d) {
      procs.textContent = "";
      (d.procs[sortBy] || []).slice(0, 10).forEach(function (p) {
        procs.appendChild(h("tr", {}, h("td", {class: "clip", title: p.cmd}, h("b", {}, p.name), h("small", {}, p.cmd)), h("td", {class: "mut hide-s"}, p.user),
          h("td", {class: "num"}, num(p.cpu, 1) + " %"), h("td", {class: "num"}, bytes(p.mem))));
      });
    }
    function paint(d) {
      var m = d.mem, t = d.temp.main, hs = d.host;
      var down = d.services.filter(function (x) { return !x.ok; }), hot = d.cpu.pct >= 92 || m.pct >= 92 || d.disk.mounts.some(function (k) { return k.pct >= 92; });
      var st = down.length ? "bad" : hot ? "warn" : "ok";
      status.className = "card status " + st; stDot.className = "dot " + st;
      stText.textContent = down.length ? (down.length === 1 ? down[0].name + " no responde" : down.length + " aplicaciones no responden: " + down.map(function (x) { return x.name; }).join(", "))
        : hot ? "El servidor va justo de recursos" : "Todo funciona con normalidad";
      stRight.textContent = hs.cpu_model.replace(/\(R\)|\(TM\)| CPU/g, "") + " · Linux " + hs.kernel + " · encendido " + dur(hs.uptime);
      setK("cpu", num(d.cpu.pct, 0), "Carga " + hs.load.map(function (x) { return num(x, 2); }).join(" · "), lvl(d.cpu.pct, S.cpu_warn, 92));
      setK("mem", num(m.pct, 0), bytes(m.used) + " de " + bytes(m.total), lvl(m.pct, S.mem_warn, 92));
      setK("temp", t == null ? "—" : num(t, 0), t == null ? "Sin sensor" : t >= S.temp_warn ? "Alta" : "Normal", t == null ? "" : lvl(t, S.temp_warn, S.temp_warn + 15));
      rx.textContent = rate(d.net.rx); tx.textContent = rate(d.net.tx); nd.textContent = "Disco ↓ " + rate(d.disk.read) + " · ↑ " + rate(d.disk.write);
      var col = function (k) { return H.map(function (x) { return x[k]; }); };
      draw(K.cpu.svg, 300, 46, 100, [col("cpu")]); draw(K.mem.svg, 300, 46, 100, [col("mem")]);
      draw(K.temp.svg, 300, 46, 80, [col("temp").map(function (v) { return v == null ? 0 : Math.max(v - 20, 0); })]);
      var mx = niceMax(Math.max.apply(null, col("rx").concat(col("tx"), [0])));
      draw(nsvg, 300, 46, mx, [col("rx"), col("tx")]); draw(big, 900, 210, mx, [col("rx"), col("tx")], 3); ymax.textContent = "máx. " + rate(mx);
      svcs.textContent = "";
      d.services.forEach(function (x) {
        var name = x.link ? h("a", {href: x.link, target: "_blank", rel: "noopener noreferrer"}, x.name) : x.name;
        svcs.appendChild(li(name, x.ok ? x.ms + " ms" : "caída hace " + dur(d.t - x.since), x.ok ? "ok" : "bad"));
      });
      if (!d.services.length) svcs.appendChild(h("li", {class: "mut"}, "No hay aplicaciones vigiladas."));
      bars.textContent = "";
      bars.appendChild(meter("Memoria RAM", bytes(m.used) + " / " + bytes(m.total), m.pct, S.mem_warn, 92));
      if (m.swap_total) bars.appendChild(meter("Intercambio (swap)", bytes(m.swap_used) + " / " + bytes(m.swap_total), m.swap_used / m.swap_total * 100, 50, 80));
      d.disk.mounts.forEach(function (k) { bars.appendChild(meter("Disco · " + k.name, bytes(k.used) + " / " + bytes(k.total), k.pct, S.disk_warn, 92)); });
      if (S.mod_battery && d.battery) bars.appendChild(meter("Batería", d.battery.pct + " %", 100 - d.battery.pct, 60, 80));
      cores.textContent = "";
      d.cpu.cores.forEach(function (p, i) { cores.appendChild(meter("Núcleo " + (i + 1), num(p, 0) + " %", p, S.cpu_warn, 92)); });
      paintProcs(d);
      if (S.mod_sensors) {
        sensors.textContent = "";
        d.temp.sensors.forEach(function (x) { sensors.appendChild(li(x.name === x.chip ? x.chip : x.name, num(x.c, 1) + " °C")); });
        if (!d.temp.sensors.length) sensors.appendChild(h("li", {class: "mut"}, "Sin sensores"));
      }
    }
    every(2000, function () {
      quiet(api("GET", "/api/stats" + (H.length ? "" : "?h=1")).then(function (d) {
        if (!d.cpu) return;
        if (d.history) H = d.history; else H.push({t: d.t, cpu: d.cpu.pct, mem: d.mem.pct, temp: d.temp.main, rx: d.net.rx, tx: d.net.tx});
        while (H.length > MAXH) H.shift();
        lastD = d; paint(d);
      }));
    });
    every(30000, function () {
      quiet(api("GET", "/api/overview").then(function (o) {
        sum.textContent = "";
        if (o.containers) sum.appendChild(li("Contenedores en marcha", o.containers.running + " de " + o.containers.total, o.containers.stopped.length ? "warn" : "ok"));
        if (o.backups) [["Última copia de seguridad", o.backups.copia], ["Última actualización", o.backups.actualizacion]].forEach(function (p) {
          if (p[1]) sum.appendChild(li(p[0], when(p[1].at), p[1].ok ? "ok" : "bad"));
        });
        sum.appendChild(li("Automatizaciones activas", (o.automations.on_ || 0) + " de " + o.automations.n, o.automations.on_ ? "ok" : ""));
        o.last_runs.slice(0, 2).forEach(function (r) { sum.appendChild(li(h("span", {}, r.name, h("span", {class: "sub"}, " · última ejecución")), when(r.at), r.ok ? "ok" : "bad")); });
      }));
    });
  };

  // ---------- Aplicaciones ----------
  V.apps = function (root) {
    var grid = h("div", {class: "grid g3"}, loading()), projects = [];
    function edit(c, preset) {
      c = c || {};
      ask(c.id ? "Editar comprobación" : "Vigilar una aplicación", [
        {k: "name", label: "Nombre", value: c.name || (preset && preset.name), required: true},
        {k: "kind", label: "Tipo de comprobación", value: c.kind || "http", options: [["http", "Web (HTTP)"], ["tcp", "Puerto (TCP)"]]},
        {k: "target", label: "Dirección que se comprueba", value: c.target, required: true, placeholder: "http://host.docker.internal:8081/", hint: "Desde el panel, el propio servidor es host.docker.internal. Para TCP: equipo:puerto."},
        {k: "link", label: "Enlace público (opcional)", value: c.link, placeholder: "https://…"},
        {k: "project", label: "Contenedores asociados", value: c.project || (preset && preset.project) || "", options: [["", "Detectar por el puerto"]].concat(projects)}
      ]).then(function (v) { v.id = c.id; return api("POST", "/api/apps", v); }).then(function () { toast("Guardado"); load(); }).catch(fail);
    }
    function op(a, o, verb) {
      sure(verb + " " + a.name, o === "stop" ? "La aplicación dejará de estar disponible hasta que la inicies de nuevo." : o === "restart" ? "Estará unos segundos sin responder mientras arranca." : "Se iniciarán sus contenedores.", verb, o === "stop").then(function () {
        toast("En curso…");
        return api("POST", "/api/apps/group/" + encodeURIComponent(a.key) + "/" + o).then(function () { toast(a.name + ": hecho"); load(); });
      }).catch(fail);
    }
    function load() {
      return api("GET", "/api/apps").then(function (d) {
        projects = d.projects; grid.textContent = "";
        d.apps.forEach(function (a) {
          var run = a.containers.filter(function (c) { return c.state === "running"; }).length, n = a.containers.length, c = a.check, known = c && c.ok !== undefined;
          var st = known ? (c.ok ? (n && run < n ? ["Parcial", "warn"] : ["Operativa", "ok"]) : ["Caída", "bad"]) : n ? (run === n ? ["En marcha", "ok"] : run ? ["Parcial", "warn"] : ["Parada", "bad"]) : ["Comprobando", ""];
          var lines = [];
          if (known) lines.push(c.ok ? "Responde en " + c.ms + " ms · " + c.detail : "Sin respuesta · " + c.detail);
          else if (!c) lines.push("Sin comprobación de respuesta");
          lines.push(!n ? "Sin contenedores asociados" : n === 1 ? "1 contenedor" + (run ? "" : " parado") : run + " de " + n + " contenedores en marcha");
          var isSelf = a.containers.some(function (x) { return x.self; }), hist = known ? c.hist.slice(-30) : null, pad = [];
          if (hist) for (var i = hist.length; i < 30; i++) pad.push(h("i", {class: "e"}));
          var host = a.link ? a.link.replace(/^https?:\/\//, "").replace(/\/$/, "") : "";
          grid.appendChild(h("section", {class: "card app"},
            h("div", {class: "top"}, h("span", {class: "ico", "aria-hidden": "true"}, a.name.charAt(0).toUpperCase()),
              h("div", {class: "nm"}, h("b", {title: a.name}, a.name), a.link ? h("a", {href: a.link, target: "_blank", rel: "noopener noreferrer"}, host) : h("span", {}, c ? (c.kind === "tcp" ? "Puerto " + c.target.split(":").pop() : "Solo red local") : "Sin vigilar")),
              badge(st[0], st[1])),
            hist ? h("div", {class: "ticks", title: "Últimas comprobaciones"}, pad, hist.map(function (o) { return h("i", {class: o ? "" : "x"}); })) : null,
            h("div", {class: "meta"}, lines.map(function (l) { return h("div", {}, l); })),
            (n && can("operador")) || can("admin") ? h("div", {class: "acts"},
              n && can("operador") ? btn("Reiniciar", function () { op(a, "restart", "Reiniciar"); }, "sec small", "restart") : null,
              n && can("operador") && run && !isSelf ? btn("Parar", function () { op(a, "stop", "Parar"); }, "sec small", "stop") : null,
              n && can("operador") && run < n ? btn("Iniciar", function () { op(a, "start", "Iniciar"); }, "sec small", "start") : null,
              h("span", {class: "sp"}),
              can("admin") ? (c ? ib("edit", "Editar la comprobación", function () { edit(c); }) : btn("Vigilar", function () { edit(null, {name: a.name, project: a.key}); })) : null,
              can("admin") && c ? ib("trash", "Dejar de vigilar", function () {
                sure("Dejar de vigilar " + c.name, "Se quita la comprobación del panel. Los contenedores no se tocan.", "Quitar", true).then(function () { return api("DELETE", "/api/apps/" + c.id); }).then(load).catch(fail);
              }, "danger") : null) : null));
        });
      });
    }
    add(root, [h("div", {class: "head"}, h("p", {class: "mut"}, "Cada tarjeta reúne los contenedores de una aplicación y la comprobación de que responde."), can("admin") ? btn("Vigilar una dirección", function () { edit(); }, "small", "plus") : null), grid]);
    every(8000, function () { quiet(load()); });
  };

  // ---------- Docker ----------
  var STATE = {running: ["En marcha", "ok"], exited: ["Parado", ""], restarting: ["Reiniciando", "warn"], paused: ["En pausa", "warn"], created: ["Creado", ""], dead: ["Fallido", "bad"]};
  V.docker = function (root) {
    if (!B.docker) { root.appendChild(card(null, h("p", {class: "empty"}, "El panel no tiene acceso a Docker."))); return; }
    var tab = "c", body = h("div", {}, loading()), ver = h("span", {class: "chip"}, "Docker");
    var seg = h("div", {class: "seg"}, [["c", "Contenedores"], ["i", "Imágenes"], ["v", "Volúmenes"], ["n", "Redes"]].map(function (t) {
      return h("button", {type: "button", class: t[0] === tab ? "on" : "", onclick: function (e) { tab = t[0]; seg.querySelectorAll("button").forEach(function (b) { b.className = b === e.target ? "on" : ""; }); body.textContent = ""; body.appendChild(loading()); load(); }}, t[1]);
    }));
    function run(c, o) { toast("En curso…"); api("POST", "/api/docker/containers/" + c.id + "/" + o).then(function () { toast(c.name + ": hecho"); load(); }).catch(fail); }
    function act(c, o, verb) {
      if (o === "start") return run(c, o);
      sure(verb + " " + c.name, o === "stop" ? "El contenedor quedará parado hasta que lo inicies de nuevo." : "Estará unos segundos sin responder mientras arranca.", verb, o === "stop").then(function () { run(c, o); });
    }
    function showLogs(c) {
      var pre = h("pre", {class: "out"}, "Cargando…"), sel = h("select", {style: "width:auto", onchange: get}, [100, 300, 1000].map(function (n) { return h("option", {value: n, selected: n === 300}, "Últimas " + n + " líneas"); }));
      function get() { api("GET", "/api/docker/containers/" + c.id + "/logs?tail=" + sel.value).then(function (d) { pre.textContent = d.text || "(sin registros)"; pre.scrollTop = pre.scrollHeight; }).catch(function (e) { pre.textContent = e.message; }); }
      modal("Registros · " + c.name, h("div", {class: "row", style: "margin-bottom:12px"}, sel, btn("Actualizar", get, "sec small", "restart")), pre); get();
    }
    function showInfo(c) {
      api("GET", "/api/docker/containers/" + c.id).then(function (d) {
        var rows = [["Imagen", d.image], ["Estado", (STATE[d.state] || [d.state])[0] + (d.health ? " (" + d.health + ")" : "")], ["Creado", when(d.created)], ["Arrancado", when(d.started)], ["Reinicios", d.restarts],
          ["Política de reinicio", d.restart_policy || "—"], ["Aplicación", d.project || "—"], ["Orden", d.command || "—"], ["Redes", d.networks.join(", ") || "—"],
          ["Puertos", d.ports.map(function (p) { return p.public + " → " + p.private + "/" + p.proto; }).join(", ") || "—"]];
        modal(d.name, h("dl", {class: "kv"}, rows.map(function (r) { return [h("dt", {}, r[0]), h("dd", {}, String(r[1]))]; }),
          h("dt", {}, "Carpetas"), h("dd", {}, d.mounts.length ? d.mounts.map(function (m) { return h("div", {class: "mono"}, m.src + " → " + m.dst + (m.rw ? "" : " (solo lectura)")); }) : "—")),
          h("p", {class: "hint", style: "margin-top:14px"}, "Las variables de entorno no se muestran porque suelen contener contraseñas."));
      }).catch(fail);
    }
    function load() {
      if (tab === "c") return api("GET", "/api/docker/containers").then(function (d) {
        ver.textContent = "Docker " + d.version;
        var rows = d.containers.map(function (c) {
          var st = d.stats[c.id], on = c.state === "running", S = STATE[c.state] || [c.state, ""];
          var health = /\(unhealthy\)/.test(c.status) ? ["Con problemas", "bad"] : S;
          return h("tr", {}, h("td", {class: "clip", title: c.image}, h("b", {}, c.name), h("small", {}, c.image.split("@")[0])),
            h("td", {title: c.status}, badge(health[0], health[1])), h("td", {class: "mono mut hide-s"}, c.ports.filter(function (p) { return p.proto === "tcp"; }).map(function (p) { return p.public; }).join(", ") || "—"),
            h("td", {class: "num hide-s"}, st && st.cpu != null ? num(st.cpu, 1) + " %" : "—"), h("td", {class: "num hide-s"}, st ? bytes(st.mem) : "—"),
            h("td", {class: "acts"}, ib("info", "Detalles", function () { showInfo(c); }), can("operador") ? [ib("logs", "Registros", function () { showLogs(c); }),
              on ? ib("restart", "Reiniciar", function () { act(c, "restart", "Reiniciar"); }) : ib("start", "Iniciar", function () { act(c, "start", "Iniciar"); }),
              on && !c.self ? ib("stop", "Parar", function () { act(c, "stop", "Parar"); }, "danger") : null] : null));
        });
        body.textContent = ""; body.appendChild(table(["Contenedor", "Estado", "Puertos*", "#CPU*", "#Memoria*", ""], rows));
      });
      return api("GET", "/api/docker/resources").then(function (d) {
        body.textContent = "";
        if (tab === "i") {
          body.appendChild(table(["Imagen", "Identificador*", "Creada*", "Uso", "#Tamaño"], d.images.map(function (i) {
            return h("tr", {}, h("td", {}, i.tags.join(", ") || h("span", {class: "mut"}, "(sin etiqueta)")), h("td", {class: "mono mut hide-s"}, i.id), h("td", {class: "mut hide-s"}, day(i.created)), h("td", {}, i.used ? badge("En uso", "ok") : badge("Sin usar", "")), h("td", {class: "num"}, bytes(i.size)));
          })));
          if (can("admin")) body.appendChild(h("p", {class: "hint"}, btn("Borrar imágenes sin etiqueta que no se usan", function () {
            sure("Limpiar imágenes", "Se borran las imágenes sin etiqueta que no usa ningún contenedor. Las demás no se tocan.", "Borrar", true).then(function () { return api("POST", "/api/docker/prune"); }).then(function (r) { toast(r.deleted + " borradas, " + bytes(r.freed) + " liberados"); load(); }).catch(fail);
          }, "sec small", "trash")));
        } else if (tab === "v") body.appendChild(table(["Volumen", "Aplicación", "Controlador"], d.volumes.map(function (v) { return h("tr", {}, h("td", {class: "mono"}, v.name), h("td", {}, v.project || "—"), h("td", {class: "mut"}, v.driver)); })));
        else body.appendChild(table(["Red", "Controlador", "Subred"], d.networks.map(function (n) { return h("tr", {}, h("td", {}, n.name), h("td", {class: "mut"}, n.driver), h("td", {class: "mono"}, n.subnet || "—")); })));
      });
    }
    add(root, [h("div", {class: "head"}, seg, ver), h("section", {class: "card flush"}, body)]);
    every(5000, function () { if (tab === "c" || body.querySelector(".empty")) quiet(load()); });
  };

  // ---------- Archivos ----------
  V.files = function (root) {
    if (!B.files) { root.appendChild(card(null, h("p", {class: "empty"}, "No hay ninguna carpeta del servidor montada en el panel."))); return; }
    var crumbs = h("div", {class: "crumbs"}), body = h("div", {}, loading()), count = h("span", {class: "mut", style: "font-size:13px"});
    function open(path) {
      api("GET", "/api/files?path=" + encodeURIComponent(path)).then(function (d) {
        crumbs.textContent = "";
        var parts = d.path ? d.path.split("/") : [];
        crumbs.appendChild(h("button", {type: "button", onclick: function () { open(""); }}, d.label));
        parts.forEach(function (p, i) { add(crumbs, ["/", h("button", {type: "button", onclick: function () { open(parts.slice(0, i + 1).join("/")); }}, p)]); });
        var rows = d.items.map(function (it) {
          var full = (d.path ? d.path + "/" : "") + it.name;
          return h("tr", {class: "click", onclick: function () { it.dir ? open(full) : show(full, it); }}, h("td", {}, h("span", {class: "fname" + (it.dir ? " dir" : "")}, icon(it.dir ? "files" : "file"), it.name)),
            h("td", {class: "num"}, it.dir ? "—" : bytes(it.size)), h("td", {class: "num mut hide-s"}, day(it.mtime)));
        });
        body.textContent = "";
        body.appendChild(rows.length ? table(["Nombre", "#Tamaño", "#Modificado*"], rows) : h("p", {class: "empty"}, "Carpeta vacía."));
        count.textContent = d.items.length + " elementos" + (d.more ? " (" + d.more + " más sin mostrar)" : "");
      }).catch(fail);
    }
    function show(path, it) {
      var dl = h("a", {class: "btn sec small", href: "/api/files/download?path=" + encodeURIComponent(path)}, icon("download"), "Descargar");
      if (it.size > 5 * 1048576) { modal(it.name, h("p", {class: "mut", style: "margin-bottom:14px"}, bytes(it.size) + " · demasiado grande para verlo aquí."), dl); return; }
      api("GET", "/api/files/view?path=" + encodeURIComponent(path)).then(function (v) {
        modal(it.name, h("div", {class: "row", style: "margin-bottom:12px"}, dl, h("span", {class: "mut"}, bytes(v.size) + (v.truncated ? " · se muestra el principio" : ""))),
          v.binary ? h("p", {class: "mut"}, "Archivo binario: no se puede mostrar como texto.") : h("pre", {class: "out"}, v.text));
      }).catch(fail);
    }
    add(root, [h("section", {class: "card flush"}, h("div", {class: "head"}, crumbs, count), body), h("p", {class: "hint"}, "Solo lectura. Las claves SSH, los archivos .env y otros secretos no se muestran.")]);
    open("");
  };

  // ---------- Terminal ----------
  V.terminal = function (root) {
    if (!B.settings.terminal) { root.appendChild(card(null, h("p", {class: "empty"}, "La terminal está desactivada en Configuración."))); return; }
    var scr = h("div", {class: "scr"}, "Escribe «help» para ver los comandos disponibles.\n\n"), hist = [], pos = 0;
    var inp = h("input", {autocomplete: "off", autocapitalize: "none", spellcheck: "false", "aria-label": "Comando", onkeydown: function (e) {
      if (e.key === "ArrowUp" && pos > 0) { inp.value = hist[--pos]; e.preventDefault(); }
      else if (e.key === "ArrowDown") { pos = Math.min(pos + 1, hist.length); inp.value = hist[pos] || ""; e.preventDefault(); }
    }});
    var form = h("form", {onsubmit: function (e) {
      e.preventDefault();
      var cmd = inp.value.trim(); inp.value = ""; if (!cmd) return;
      hist.push(cmd); pos = hist.length;
      if (cmd === "clear") { scr.textContent = ""; return; }
      add(scr, [h("span", {class: "c"}, "$ " + cmd + "\n")]);
      api("POST", "/api/console", {cmd: cmd}).then(function (d) { return d.out; }, function (er) { return er.message; }).then(function (out) {
        add(scr, [out + "\n\n"]); scr.scrollTop = scr.scrollHeight;
      });
    }}, h("span", {}, "$"), inp);
    add(root, [h("div", {class: "term", onclick: function (e) { if (e.target === scr && !String(getSelection())) inp.focus(); }},
      h("div", {class: "tb"}, h("span", {}, B.user.username + "@" + (B.host || "servidor")), h("span", {}, "consola restringida")), scr, form),
      h("p", {class: "hint"}, "No es una shell: solo acepta una lista cerrada de comandos de consulta y de control de contenedores. Cada comando queda en el registro de actividad.")]);
    inp.focus();
  };

  // ---------- Red ----------
  V.net = function (root) {
    var ifs = h("div", {}, loading()), devs = h("div", {}, loading()), ports = h("div", {}, loading()), ts = h("div"), tsCard = panel("Tailscale", null, ts), info = h("span", {class: "mut", style: "font-size:13px"});
    tsCard.hidden = true;
    function load() {
      return api("GET", "/api/net").then(function (d) {
        var on = d.devices.filter(function (x) { return x.online; }).length;
        info.textContent = on + " conectados de " + d.devices.length + " · " + d.lan;
        devs.textContent = "";
        devs.appendChild(d.devices.length ? table(["Dispositivo", "Estado", "IP", "MAC*", "Visto*", ""], d.devices.map(function (x) {
          return h("tr", {}, h("td", {}, x.name || x.hostname ? h("b", {}, x.name || x.hostname) : h("span", {class: "mut"}, "Sin nombre"), x.name && x.hostname ? h("small", {}, x.hostname) : null),
            h("td", {}, x.online ? badge("Conectado", "ok") : badge("Ausente", "")),
            h("td", {class: "mono"}, x.ip), h("td", {class: "mono mut hide-s"}, x.mac), h("td", {class: "mut hide-s"}, x.online ? "Ahora" : when(x.last_seen)),
            h("td", {class: "acts"}, can("operador") ? [ib("edit", "Poner nombre", function () {
              ask("Nombre del dispositivo", [{k: "name", label: x.ip + " · " + x.mac, value: x.name}]).then(function (v) { return api("POST", "/api/net/device", {mac: x.mac, name: v.name}); }).then(load).catch(fail);
            }), x.online ? null : ib("trash", "Olvidar dispositivo", function () { api("POST", "/api/net/device", {mac: x.mac, forget: true}).then(load).catch(fail); }, "danger")] : null));
        })) : h("p", {class: "empty"}, "Todavía no se ha visto ningún dispositivo."));
        ports.textContent = "";
        ports.appendChild(table(["#Puerto", "Alcance", "Servicio"], d.ports.listening.map(function (p) {
          return h("tr", {}, h("td", {class: "num"}, p.port), h("td", {}, p.local ? badge("Local", "plain") : badge("Red", "plain ok")), h("td", {}, p.owner || h("span", {class: "mut"}, "Sistema")));
        })));
        ports.appendChild(h("p", {class: "hint"}, d.ports.established + " conexiones TCP abiertas ahora mismo."));
        tsCard.hidden = !d.tailscale;
        if (d.tailscale) {
          ts.textContent = "";
          ts.appendChild(table(["Equipo", "Estado", "IP", "Sistema*"], d.tailscale.peers.map(function (p) {
            return h("tr", {}, h("td", {}, h("b", {}, p.name), p.me ? h("span", {class: "mut"}, " · este servidor") : null), h("td", {}, p.online ? badge("Conectado", "ok") : badge("Desconectado", "")),
              h("td", {class: "mono"}, p.ip), h("td", {class: "mut hide-s"}, p.os));
          })));
        }
      });
    }
    var scanB = btn("Buscar dispositivos", function () {
      scanB.disabled = true; scanB.lastChild.textContent = "Buscando…";
      api("POST", "/api/net/scan").then(function (r) { toast(r.alive + " equipos responden"); return load(); }).catch(fail).then(function () { scanB.disabled = false; scanB.lastChild.textContent = "Buscar dispositivos"; });
    }, "small", "search");
    add(root, [panel("Dispositivos en la red local", [info, can("operador") ? scanB : null], devs),
      h("div", {class: "grid g2", style: "align-items:start"}, panel("Interfaces", null, ifs), panel("Puertos a la escucha", null, ports)), tsCard]);
    every(15000, function () { quiet(load()); });
    every(2000, function () {
      quiet(api("GET", "/api/stats").then(function (d) {
        if (!d.net) return;
        ifs.textContent = "";
        ifs.appendChild(table(["Interfaz", "#Bajada", "#Subida", "#Recibido", "#Enviado"], d.net.ifaces.map(function (f) {
          return h("tr", {}, h("td", {}, h("b", {}, f.name)), h("td", {class: "num"}, rate(f.rx)), h("td", {class: "num"}, rate(f.tx)), h("td", {class: "num"}, bytes(f.rx_total)), h("td", {class: "num"}, bytes(f.tx_total)));
        })));
      }));
    });
  };

  // ---------- Usuarios ----------
  var ROLE_OPTS = [["lector", "Lector"], ["operador", "Operador"], ["admin", "Administrador"]];
  V.users = function (root) {
    var body = h("div", {}, loading());
    function save(u, data, msg) { api("POST", "/api/users/" + u.id, data).then(function () { toast(msg || "Guardado"); load(); }).catch(function (e) { fail(e); load(); }); }
    function load() {
      api("GET", "/api/users").then(function (d) {
        body.textContent = "";
        body.appendChild(table(["Usuario", "Rol", "Activo", "Seguridad*", "Último acceso*", ""], d.users.map(function (u) {
          return h("tr", {}, h("td", {}, h("div", {class: "row nw"}, h("span", {class: "avatar", "aria-hidden": "true"}, u.username.charAt(0).toUpperCase()), h("div", {}, h("b", {}, u.username), u.id === B.user.id ? h("span", {class: "mut"}, " · tú") : null))),
            h("td", {}, h("select", {style: "width:auto", "aria-label": "Rol", onchange: function (e) { save(u, {role: e.target.value}); }}, ROLE_OPTS.map(function (o) { return h("option", {value: o[0], selected: o[0] === u.role}, o[1]); }))),
            h("td", {}, h("input", {type: "checkbox", class: "switch", checked: !!u.active, "aria-label": "Activo", onchange: function (e) { save(u, {active: e.target.checked}); }})),
            h("td", {class: "hide-s"}, u.twofa ? badge("Dos pasos", "ok") : badge("Solo contraseña", "")),
            h("td", {class: "mut hide-s nowrap"}, u.last_login ? when(u.last_login) : "Nunca"),
            h("td", {class: "acts"}, btn("Contraseña", function () {
              ask("Nueva contraseña para " + u.username, [{k: "password", label: "Contraseña (mínimo 10 caracteres)", type: "password", required: true}]).then(function (v) { save(u, {password: v.password}, "Contraseña cambiada"); });
            }), u.twofa ? btn("Quitar dos pasos", function () { sure("Quitar la verificación en dos pasos", u.username + " volverá a entrar solo con contraseña.", "Quitar", true).then(function () { save(u, {reset_2fa: true}); }); }) : null,
            u.id !== B.user.id ? ib("trash", "Eliminar cuenta", function () { sure("Eliminar la cuenta " + u.username, "La cuenta se borra y su sesión se cierra. No se puede deshacer.", "Eliminar", true).then(function () { return api("DELETE", "/api/users/" + u.id); }).then(load).catch(fail); }, "danger") : null));
        })));
      }).catch(fail);
    }
    var yes = "Sí", no = "—";
    add(root, [panel("Cuentas", btn("Crear usuario", function () {
      ask("Crear usuario", [{k: "username", label: "Usuario", required: true}, {k: "password", label: "Contraseña (mínimo 10 caracteres)", type: "password", required: true}, {k: "role", label: "Rol", value: "lector", options: ROLE_OPTS}], "Crear")
        .then(function (v) { return api("POST", "/api/users", v); }).then(function () { toast("Usuario creado"); load(); }).catch(fail);
    }, "small", "plus"), body),
    panel("Permisos de cada rol", null, table(["Permiso", "Lector", "Operador", "Administrador"], [
      ["Ver Dashboard, Aplicaciones, Docker y Red", yes, yes, yes], ["Iniciar, parar y reiniciar contenedores", no, yes, yes], ["Ver registros y usar la Terminal", no, yes, yes],
      ["Buscar dispositivos y ejecutar automatizaciones", no, yes, yes], ["Explorar Archivos", no, no, yes], ["Crear automatizaciones, plugins y configuración", no, no, yes], ["Gestionar usuarios", no, no, yes]
    ].map(function (r) { return h("tr", {}, r.map(function (c, i) { return h("td", {class: c === no ? "mut" : ""}, i && c === yes ? badge("Sí", "ok plain") : c); })); })))]);
    load();
  };

  // ---------- Automatizaciones ----------
  var DAYS = ["L", "M", "X", "J", "V", "S", "D"], OPW = {restart: "Reiniciar", start: "Iniciar", stop: "Parar"};
  V.autos = function (root) {
    var list = h("div", {}, loading()), runs = h("div", {}, loading()), formBox = h("div"), D = {containers: [], apps: []};
    function trigText(t) {
      if (t.kind === "interval") return "Cada " + (t.minutes % 60 ? t.minutes + " min" : t.minutes / 60 + " h");
      if (t.kind === "daily") return "Cada día a las " + t.time;
      if (t.kind === "weekly") return t.days.map(function (d) { return DAYS[d]; }).join(" ") + " a las " + t.time;
      var a = D.apps.filter(function (x) { return x.id === t.app; })[0];
      return "Si " + (a ? a.name : "una aplicación eliminada") + " lleva " + t.minutes + " min caída";
    }
    function actText(a) { return a.kind === "container" ? OPW[a.op] + " " + a.name : a.kind === "http" ? a.method + " " + a.url : "Borrar imágenes sin usar"; }
    function op(a, o) { return api("POST", "/api/automations/" + a.id + "/" + o); }
    function load() {
      return api("GET", "/api/automations").then(function (d) {
        var first = !D.loaded; D = d; D.loaded = true;
        if (first && can("admin")) buildForm();
        list.textContent = "";
        list.appendChild(d.items.length ? table(["Tarea", "Estado", "Cuándo", "Próxima*", "Último resultado*", ""], d.items.map(function (a) {
          return h("tr", {}, h("td", {class: "clip"}, h("b", {}, a.name), h("small", {}, actText(a.action))), h("td", {}, a.enabled ? badge("Activa", "ok") : badge("En pausa", "")),
            h("td", {}, trigText(a.trig)), h("td", {class: "mut hide-s nowrap"}, a.enabled ? (a.trig.kind === "down" ? "Cuando ocurra" : when(a.next_run)) : "—"),
            h("td", {class: "hide-s"}, a.last_run ? h("div", {class: "row nw"}, badge(a.last_ok ? "Correcto" : "Error", a.last_ok ? "ok" : "bad"), h("span", {class: "mut", style: "white-space:nowrap"}, when(a.last_run))) : h("span", {class: "mut"}, "Aún no se ha ejecutado")),
            h("td", {class: "acts"}, can("operador") ? ib("start", "Ejecutar ahora", function () { toast("Ejecutando…"); op(a, "run").then(function (r) { toast(a.name + ": " + r.msg, !r.ok); load(); }).catch(fail); }) : null,
              can("admin") ? [ib(a.enabled ? "pause" : "restart", a.enabled ? "Pausar" : "Activar", function () { op(a, "toggle").then(load).catch(fail); }),
                ib("trash", "Eliminar", function () { sure("Eliminar la tarea " + a.name, "Dejará de ejecutarse. El historial se conserva.", "Eliminar", true).then(function () { return op(a, "delete"); }).then(load).catch(fail); }, "danger")] : null));
        })) : h("p", {class: "empty"}, "No hay tareas automáticas todavía." + (can("admin") ? " Crea la primera con el formulario de abajo." : "")));
        runs.textContent = "";
        runs.appendChild(d.runs.length ? table(["Fecha", "Tarea", "Resultado", "Detalle*", "Lanzada por*"], d.runs.map(function (r) {
          return h("tr", {}, h("td", {class: "mut", style: "white-space:nowrap"}, when(r.at)), h("td", {}, r.name), h("td", {}, badge(r.ok ? "Correcto" : "Error", r.ok ? "ok" : "bad")), h("td", {class: "mut hide-s"}, r.msg), h("td", {class: "mut hide-s"}, r.by));
        })) : h("p", {class: "empty"}, "Sin ejecuciones todavía."));
      });
    }
    function buildForm() {
      function sel(opts) { return h("select", {}, opts.map(function (o) { return h("option", {value: o[0]}, o[1]); })); }
      var name = h("input", {required: true, maxlength: 60, placeholder: "Reinicio semanal de…"}), tk = sel([["daily", "Cada día a una hora"], ["weekly", "Días de la semana"], ["interval", "Cada cierto tiempo"], ["down", "Cuando una aplicación se cae"]]);
      var ak = sel([["container", "Actuar sobre un contenedor"], ["http", "Llamar a una dirección web"], ["prune", "Borrar imágenes de Docker sin usar"]]);
      var tBox = h("div", {class: "form full"}), aBox = h("div", {class: "form full"}), T = {}, A = {};
      function f(label, input) { return h("div", {}, h("label", {}, label), input); }
      function drawT() {
        tBox.textContent = ""; T = {};
        if (tk.value === "interval") add(tBox, [f("Cada cuántos minutos", T.minutes = h("input", {type: "number", min: 1, max: 43200, value: 60, required: true}))]);
        else if (tk.value === "down") add(tBox, [f("Aplicación vigilada", T.app = sel(D.apps.map(function (a) { return [a.id, a.name]; }))), f("Minutos caída antes de actuar", T.minutes = h("input", {type: "number", min: 1, max: 1440, value: 3, required: true}))]);
        else {
          add(tBox, [f("Hora", T.time = h("input", {type: "time", value: "04:00", required: true}))]);
          if (tk.value === "weekly") { T.days = DAYS.map(function (d, i) { return h("input", {type: "checkbox", value: i, "aria-label": d}); }); add(tBox, [f("Días", h("div", {class: "row", style: "min-height:36px;gap:12px"}, T.days.map(function (c, i) { return h("label", {class: "check", style: "margin:0"}, c, DAYS[i]); })))]); }
        }
      }
      function drawA() {
        aBox.textContent = ""; A = {};
        if (ak.value === "container") add(aBox, [f("Operación", A.op = sel([["restart", "Reiniciar"], ["start", "Iniciar"], ["stop", "Parar"]])), f("Contenedor", A.name = sel(D.containers.map(function (c) { return [c, c]; })))]);
        else if (ak.value === "http") add(aBox, [f("Método", A.method = sel([["GET", "GET"], ["POST", "POST"]])), f("Dirección", A.url = h("input", {type: "url", placeholder: "https://…", required: true}))]);
      }
      tk.onchange = drawT; ak.onchange = drawA; drawT(); drawA();
      formBox.appendChild(card("Nueva tarea", h("form", {class: "form", onsubmit: function (e) {
        e.preventDefault();
        var trig = {kind: tk.value}, act = {kind: ak.value}, k;
        for (k in T) trig[k] = k === "days" ? T.days.filter(function (c) { return c.checked; }).map(function (c) { return +c.value; }) : T[k].value;
        for (k in A) act[k] = A[k].value;
        api("POST", "/api/automations", {name: name.value, trig: trig, action: act}).then(function () { toast("Tarea creada"); name.value = ""; load(); }).catch(fail);
      }}, f("Nombre", name), f("Cuándo", tk), f("Qué hace", ak), tBox, aBox, h("div", {class: "act full"}, h("button", {}, icon("plus"), "Crear tarea")))));
    }
    add(root, [panel("Tareas", null, list), formBox, panel("Historial de ejecuciones", null, runs)]);
    every(15000, function () { quiet(load()); });
  };

  // ---------- Plugins ----------
  var MODS = [["mod_backups", "Copias de seguridad", "Muestra en el Dashboard cuándo se hizo la última copia y la última actualización, y si fueron bien."],
    ["mod_tailscale", "Tailscale", "Añade a Red los equipos de tu red privada de Tailscale."], ["mod_sensors", "Sensores", "Temperaturas de la placa y la CPU en el Dashboard."],
    ["mod_battery", "Batería", "Nivel de batería del portátil en el Dashboard."]];
  V.plugins = function (root) {
    var inst = h("div", {}, loading()), file = h("input", {type: "file", accept: ".zip", required: true, "aria-label": "Archivo .zip del plugin"});
    function load() {
      api("GET", "/api/plugins").then(function (d) {
        B.plugins = d.installed; nav();
        inst.textContent = "";
        inst.appendChild(d.installed.length ? table(["Plugin", "Versión", ""], d.installed.map(function (p) {
          return h("tr", {}, h("td", {}, h("a", {href: "#plugin/" + p.id}, h("b", {}, p.name)), h("small", {style: "font-family:inherit"}, p.description)), h("td", {class: "mono mut"}, p.version || "—"),
            h("td", {class: "acts"}, can("admin") ? ib("trash", "Desinstalar", function () { sure("Desinstalar " + p.name, "El plugin se borra del panel y su sección desaparece.", "Desinstalar", true).then(function () { return api("DELETE", "/api/plugins/" + p.id); }).then(load).catch(fail); }, "danger") : null));
        })) : h("p", {class: "empty"}, "No hay plugins instalados."));
      }).catch(fail);
    }
    add(root, [card("Módulos incluidos", h("ul", {class: "list"}, MODS.map(function (m) {
      return h("li", {}, h("div", {}, h("div", {style: "font-weight:550"}, m[1]), h("div", {class: "mut", style: "font-size:13px"}, m[2])),
        h("input", {type: "checkbox", class: "switch", checked: !!B.settings[m[0]], disabled: !can("admin"), "aria-label": "Activar " + m[1], onchange: function (e) {
          var b = {}; b[m[0]] = e.target.checked;
          api("POST", "/api/settings", b).then(function (st) { B.settings = st; toast(m[1] + (st[m[0]] ? " activado" : " desactivado")); }).catch(fail);
        }}));
    }))), panel("Plugins instalados", null, inst),
    can("admin") ? card("Instalar un plugin", h("form", {class: "row", onsubmit: function (e) {
      e.preventDefault();
      var fd = new FormData(); fd.append("file", file.files[0]);
      api("POST", "/api/plugins/install", fd).then(function (m) { toast(m.name + " instalado"); file.value = ""; load(); }).catch(fail);
    }}, h("div", {style: "flex:1;min-width:220px"}, file), h("button", {}, icon("plus"), "Instalar")),
    h("p", {class: "hint"}, "Un plugin es un .zip con un manifest.json y un index.html autónomo. Aparece como una sección más y se ejecuta aislado: recibe un resumen de métricas del panel, pero no puede usar tu sesión ni tocar el servidor. ",
      h("a", {href: "/api/plugins/ejemplo.zip"}, "Descargar un plugin de ejemplo"), ".")) : null]);
    load();
  };
  V.plugin = function (root, id) {
    var fr = h("iframe", {class: "plugin", sandbox: "allow-scripts", src: "/plugins/" + encodeURIComponent(id) + "/", title: "Plugin"});
    root.appendChild(fr);
    every(3000, function () {
      quiet(api("GET", "/api/stats").then(function (d) {
        if (!d.cpu || !fr.contentWindow) return;
        fr.contentWindow.postMessage({type: "nexo:stats", data: {t: d.t, host: {name: d.host.name, uptime: d.host.uptime, load: d.host.load, cores: d.host.cores}, cpu: d.cpu, mem: d.mem, temp: d.temp.main,
          net: {rx: d.net.rx, tx: d.net.tx}, disk: d.disk, services: d.services.map(function (x) { return {name: x.name, ok: x.ok, ms: x.ms}; })}}, "*");
      }));
    });
  };

  // ---------- Configuración ----------
  V.settings = function (root) {
    var S = B.settings;
    function f(label, input) { return h("div", {}, h("label", {}, label), input); }
    if (can("admin")) {
      var I = {name: h("input", {value: S.name, maxlength: 40, required: true}), lan: h("input", {value: S.lan, required: true})};
      [["cpu_warn", "Aviso de CPU (%)"], ["mem_warn", "Aviso de memoria (%)"], ["disk_warn", "Aviso de disco (%)"], ["temp_warn", "Aviso de temperatura (°C)"]].forEach(function (p) { I[p[0]] = h("input", {type: "number", min: 1, max: 110, value: S[p[0]], required: true, "data-l": p[1]}); });
      var term = h("input", {type: "checkbox", class: "switch", checked: !!S.terminal});
      root.appendChild(card("General", h("form", {class: "form", onsubmit: function (e) {
        e.preventDefault();
        var b = {terminal: term.checked}; for (var k in I) b[k] = I[k].value;
        api("POST", "/api/settings", b).then(function (st) { B.settings = st; $("brand").textContent = st.name; document.title = st.name; toast("Configuración guardada"); nav(); }).catch(fail);
      }}, f("Nombre del panel", I.name), f("Red local que se escanea", I.lan), ["cpu_warn", "mem_warn", "disk_warn", "temp_warn"].map(function (k) { return f(I[k].getAttribute("data-l"), I[k]); }),
        h("div", {class: "full", style: "margin-top:8px"}, h("label", {class: "check"}, term, "Terminal web activada")), h("div", {class: "act full"}, h("button", {}, "Guardar cambios")))));
    }
    var cur = h("input", {type: "password", autocomplete: "current-password", required: true}), nw = h("input", {type: "password", autocomplete: "new-password", minlength: 10, required: true});
    var two = h("div");
    function draw2() {
      two.textContent = "";
      if (B.user.twofa) add(two, [h("p", {style: "margin-bottom:12px"}, badge("Activada", "ok")), h("p", {class: "mut", style: "margin-bottom:14px"}, "Al entrar se pide un código de tu aplicación de autenticación además de la contraseña."), btn("Desactivar", function () {
        ask("Desactivar la verificación en dos pasos", [{k: "password", label: "Tu contraseña", type: "password", required: true}], "Desactivar").then(function (v) { return api("POST", "/api/account/2fa", {step: "disable", password: v.password}); })
          .then(function () { B.user.twofa = false; draw2(); toast("Desactivada"); }).catch(fail);
      }, "sec")]);
      else add(two, [h("p", {style: "margin-bottom:12px"}, badge("Desactivada", "warn")), h("p", {class: "mut", style: "margin-bottom:14px"}, "Recomendable: el panel puede parar contenedores y leer archivos, y es accesible desde internet."), btn("Activar", function () {
        api("POST", "/api/account/2fa", {step: "start"}).then(function (d) {
          return ask("Verificación en dos pasos", [{k: "code", label: "Código de 6 cifras", required: true, hint: "Añade una cuenta en tu aplicación de autenticación (Google Authenticator, 1Password, Aegis…) escribiendo esta clave: " + d.secret.replace(/(.{4})/g, "$1 ").trim() + ". Después escribe aquí el código que te muestre."}], "Activar");
        }).then(function (v) { return api("POST", "/api/account/2fa", {step: "confirm", code: v.code}); }).then(function () { B.user.twofa = true; draw2(); toast("Verificación en dos pasos activada"); }).catch(fail);
      }, "")]);
    }
    draw2();
    root.appendChild(h("div", {class: "grid g2"}, card("Cambiar mi contraseña", h("form", {onsubmit: function (e) {
      e.preventDefault();
      api("POST", "/api/account/password", {current: cur.value, "new": nw.value}).then(function () { cur.value = nw.value = ""; toast("Contraseña cambiada. Las demás sesiones se han cerrado."); }).catch(fail);
    }}, h("label", {}, "Contraseña actual"), cur, h("label", {}, "Nueva ", h("span", {class: "opt"}, "mínimo 10 caracteres")), nw, h("div", {style: "margin-top:16px"}, h("button", {}, "Cambiar contraseña")))), card("Verificación en dos pasos", two)));
    if (can("admin")) {
      var log = h("div", {}, loading()); root.appendChild(panel("Registro de actividad", null, log));
      api("GET", "/api/audit").then(function (d) {
        log.textContent = "";
        log.appendChild(table(["Fecha", "Usuario", "Acción", "Detalle", "IP*"], d.items.map(function (r) {
          return h("tr", {}, h("td", {class: "mut", style: "white-space:nowrap"}, when(r.at)), h("td", {}, h("b", {}, r.user)), h("td", {}, r.action), h("td", {class: "mut"}, r.detail), h("td", {class: "mono mut hide-s"}, r.ip));
        })));
      }).catch(fail);
    }
  };

  // ---------- navegación ----------
  var GROUPS = [["General", [["dashboard", "Dashboard", "", "Estado general del servidor"], ["apps", "Aplicaciones", "", "Tus aplicaciones y si responden"], ["docker", "Docker", "", "Contenedores, imágenes, volúmenes y redes"]]],
    ["Herramientas", [["files", "Archivos", "admin", "Almacenamiento del servidor"], ["terminal", "Terminal", "operador", "Consola web restringida"], ["net", "Red", "", "Dispositivos, puertos y conexiones"], ["autos", "Automatizaciones", "", "Tareas automáticas"]]],
    ["Sistema", [["users", "Usuarios", "admin", "Cuentas, roles y permisos"], ["plugins", "Plugins", "", "Módulos adicionales"], ["settings", "Configuración", "", "Ajustes del panel y de tu cuenta"]]]];
  var SECTIONS = [].concat.apply([], GROUPS.map(function (g) { return g[1]; }));
  function route() { var p = location.hash.slice(1).split("/"); return {id: p[0] || "dashboard", arg: p[1] ? decodeURIComponent(p[1]) : ""}; }
  function nav() {
    var n = $("nav"), r = route(); n.textContent = "";
    GROUPS.forEach(function (g) {
      var items = g[1].filter(function (x) { return !x[2] || can(x[2]); });
      if (!items.length) return;
      n.appendChild(h("div", {class: "sep"}, g[0]));
      items.forEach(function (x) { n.appendChild(h("a", {href: "#" + x[0], class: r.id === x[0] ? "on" : "", "aria-current": r.id === x[0] ? "page" : null}, icon(x[0]), x[1])); });
    });
    if (B.plugins.length) {
      n.appendChild(h("div", {class: "sep"}, "Plugins"));
      B.plugins.forEach(function (p) { n.appendChild(h("a", {href: "#plugin/" + p.id, class: r.id === "plugin" && r.arg === p.id ? "on" : ""}, icon("plugin"), p.name)); });
    }
  }
  function show() {
    timers.forEach(clearInterval); timers = [];
    document.querySelectorAll("dialog").forEach(function (d) { d.close(); });
    var r = route(), sec = SECTIONS.filter(function (x) { return x[0] === r.id; })[0], view = $("view");
    if (r.id === "plugin") { var p = B.plugins.filter(function (x) { return x.id === r.arg; })[0]; sec = p ? ["plugin", p.name, "", p.description || "Plugin"] : null; }
    if (!sec || (sec[2] && !can(sec[2]))) { location.hash = "#dashboard"; return; }
    $("title").textContent = sec[1]; $("subtitle").textContent = sec[3]; document.title = sec[1] + " · " + B.settings.name;
    view.textContent = ""; nav();
    V[sec[0]](view, r.arg);
    window.scrollTo(0, 0);
  }
  api("GET", "/api/boot").then(function (b) {
    B = b;
    $("av").textContent = b.user.username.charAt(0).toUpperCase(); $("me-name").textContent = b.user.username; $("me-role").textContent = ROLE[b.user.role];
    if (b.host) { $("host").textContent = b.host; $("host").hidden = false; }
    window.addEventListener("hashchange", show); show();
  }).catch(fail);
})();
