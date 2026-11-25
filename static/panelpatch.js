"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", chart: "profile", busy: false,
  pair: null, pairIndex: null, pairPhoto: null, pairOpen: false};
const settings = [...document.querySelectorAll("[data-setting]")];

async function api(path, options) {
  const response = await fetch("/panelpatch" + path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败，请检查输入后重试。");
  return body;
}

function route(tail) {
  return "/cards/" + state.card.id + tail;
}

function savedQuery() {
  return "?revision=" + state.card.revision;
}

function notice(message, target = "notice") {
  const element = get(target);
  element.textContent = message;
  element.hidden = !message;
}

async function action(work, target = "notice") {
  if (state.busy) return;
  state.busy = true;
  document.querySelectorAll("button, select").forEach((node) => { node.disabled = true; });
  notice("", target);
  try {
    await work();
  } catch (error) {
    notice(error.message, target);
  } finally {
    state.busy = false;
    document.querySelectorAll("button, select").forEach((node) => { node.disabled = false; });
  }
}

async function library() {
  const {cards} = await api("/cards");
  const select = get("library");
  select.replaceChildren(new Option("选取已存卡片", ""));
  for (const card of cards) select.append(new Option(card.name, card.id));
  select.value = state.card?.id || "";
  const other = get("pair-card");
  const chosen = state.pair?.other.id || other.value;
  other.replaceChildren(new Option("选择另一张卡", ""));
  for (const card of cards) {
    if (card.id !== state.card?.id) other.append(new Option(card.name, card.id));
  }
  other.value = [...other.options].some((option) => option.value === chosen) ? chosen : "";
}

function markPair(ctx, item, colour) {
  if (!item) return;
  ctx.strokeStyle = colour;
  ctx.lineWidth = 1;
  if (item.status === "paired") ctx.strokeRect(item.x - 4, item.y - 3, 8, 6);
  else if (item.status === "clipped") {
    ctx.beginPath();
    ctx.moveTo(item.x - 3, item.y - 3);
    ctx.lineTo(item.x + 3, item.y + 3);
    ctx.moveTo(item.x + 3, item.y - 3);
    ctx.lineTo(item.x - 3, item.y + 3);
    ctx.stroke();
  }
}

function paintPairOverlay(ctx, items, active) {
  for (const item of items) markPair(ctx, item, item.status === "paired" ? "#67d9c1" : "#8196a6");
  if (active) {
    ctx.strokeStyle = "#f6e39b";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(active.x + .5, active.y + .5, 8, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function paintSource() {
  const canvas = get("capture");
  const ctx = canvas.getContext("2d");
  const {result, card, probe} = state;
  const switched = Boolean(state.pairOpen && state.pair && state.pairPhoto);
  const shown = switched ? state.pair.other : card;
  const photo = switched ? state.pairPhoto : state.photo;
  if (!photo) return;
  canvas.width = shown.width;
  canvas.height = shown.height;
  ctx.drawImage(photo, 0, 0);
  const cfg = shown.settings;
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#7cadd4";
  ctx.setLineDash([6,5]);
  ctx.strokeRect(cfg.left,cfg.top,cfg.right-cfg.left,cfg.bottom-cfg.top);
  ctx.setLineDash([]);
  const cut = cfg.focus >= cfg.left && cfg.focus <= cfg.right;
  if (cut) {
    ctx.strokeStyle = "#e4deab";
    ctx.beginPath();
    ctx.moveTo(cfg.focus,cfg.top);
    ctx.lineTo(cfg.focus,cfg.bottom);
    ctx.stroke();
  }
  const reference = switched ? state.pair.references.other : result.reference;
  ctx.strokeStyle = "#8ee3c6";
  ctx.strokeRect(reference.x - 5, reference.y - 5, 10, 10);
  const colours = {bright: "#e5a461", dark: "#9c9bf5", within: "#84b7a8"};
  const profile = switched ? state.pair.other_items : result.profile;
  for (const row of profile) {
    ctx.fillStyle = colours[row.classification] || colours.within;
    ctx.fillRect(row.x - 1, row.y, 3, 1);
  }
  if (switched) {
    paintPairOverlay(ctx, state.pair.other_items, state.pair.pairs[state.pairIndex]?.other);
  } else {
    if (probe) {
      ctx.strokeStyle = "#30393b";
      ctx.strokeRect(probe.x - 5, probe.y - 5, 10, 10);
    }
    if (state.pair) paintPairOverlay(ctx, state.pair.items, state.pair.pairs[state.pairIndex]?.primary);
  }
}

function paintChart() {
  const canvas = get("chart");
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  const {result, card} = state;
  const cfg = card.settings;
  const coverage = state.chart === "coverage";
  const lo = coverage ? cfg.left : cfg.top;
  const hi = coverage ? cfg.right : cfg.bottom;
  const bound = coverage ? Math.max(1, ...result.coverage.map((row) => Math.max(row.bright, row.dark)))
    : Math.ceil(Math.max(10, cfg.limit, ...result.profile.map((row) => Math.abs(row.delta))));
  const min = coverage ? 0 : -bound;
  const xAt = (x) => 42 + (width - 79) * (x - lo) / Math.max(1, hi - lo);
  const yAt = (y) => height - 26 - (height - 46) * (y - min) / (bound - min);
  get("chart-title").textContent = coverage ? "各原列亮暗越限" : "原列相对亮度";
  get("chart-caption").textContent = coverage ? "琥珀偏亮 · 紫色偏暗 · 原片 X" : "相对参考 · 原片 Y";

  ctx.fillStyle = "#17232e";
  ctx.fillRect(0, 0, width, height);
  ctx.font = "12px monospace";
  ctx.fillStyle = "#aabdce";
  ctx.strokeStyle = "#344858";
  for (const level of [min, Math.round((min + bound) / 2), bound]) {
    ctx.fillText(level, 8, yAt(level) + 3);
    ctx.beginPath();
    ctx.moveTo(xAt(lo), yAt(level));
    ctx.lineTo(xAt(hi), yAt(level));
    ctx.stroke();
  }
  ctx.fillText(String(lo), xAt(lo), height - 7);
  ctx.fillText(String(hi), xAt(hi) - 15, height - 7);
  ctx.lineWidth = 2;
  const plot = (values, color) => {
    ctx.strokeStyle = color;
    ctx.beginPath();
    values.forEach(([x,y], i) => {
      if (i) ctx.lineTo(xAt(x), yAt(y));
      else ctx.moveTo(xAt(x), yAt(y));
    });
    ctx.stroke();
  };
  if (coverage) {
    plot(result.coverage.map((row) => [row.x, row.bright]), "#e4a86f");
    plot(result.coverage.map((row) => [row.x, row.dark]), "#a6a4f1");
  } else {
    plot(result.profile.map((row) => [row.y, row.delta]), "#84dbc0");
    ctx.setLineDash([5, 4]);
    plot([[lo, cfg.limit], [hi, cfg.limit]], "#e4a86f");
    plot([[lo, -cfg.limit], [hi, -cfg.limit]], "#a6a4f1");
    ctx.setLineDash([]);
  }
}

function pointLabel(point) {
  const meaning = {bright: "偏亮", dark: "偏暗", within: "限内"};
  const kind = meaning[point.classification] || "框外";
  return "(" + point.x + ", " + point.y + ") · RGB " + point.rgb.join("/") +
    " · 亮度 " + point.brightness.toFixed(2) + " · 偏差 " + signed(point.delta) + " · " + kind;
}

function signed(value) {
  return (value > 0 ? "+" : "") + value.toFixed(2);
}

function pairLabel(entry) {
  return "Y " + entry.primary.y + " ⇄ " + entry.other.y + " · ΔY " + (entry.dy > 0 ? "+" : "") +
    entry.dy + " · 偏差 " + signed(entry.primary.delta) + " / " + signed(entry.other.delta);
}

function show() {
  const {card, result} = state;
  const open = Boolean(state.pairOpen && state.pair && state.pairIndex !== null);
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("name").value = card.name;
  for (const field of settings) field.value = card.settings[field.dataset.setting];
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? result.focus;
  get("probe-y").value = state.probe?.y ?? Math.round((card.settings.top+card.settings.bottom)/2);
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  const reading = result.reading;
  const entry = open ? state.pair.pairs[state.pairIndex] : null;
  const other = open ? state.pair.other : null;
  get("card-title").textContent = other ? other.name : card.name;
  get("dimensions").textContent = other
    ? other.width + " × " + other.height + " px · " + other.photo_name + " · 原片 X " + other.focus
    : card.width + " × " + card.height + " px · " + card.photo_name;
  get("delta-value").textContent = open ? signed(entry.other.delta) : reading ? signed(reading.delta_mean) : "—";
  get("reference-info").textContent = "实际参考亮度 " +
    (open ? state.pair.references.other.brightness : result.reference.brightness).toFixed(2);
  get("delta-unit").textContent = "亮度级";
  get("measurement-state").textContent = open
    ? "另一张卡 · 限值 ±" + other.limit
    : "原片 X " + result.focus;
  get("selected-level").textContent = open
    ? (entry.other.classification === "bright" ? "偏亮" : "偏暗") + " · 原片 Y " + entry.other.y +
      " · 与本卡 Y " + entry.primary.y + " 相差 " + (entry.dy > 0 ? "+" : "") + entry.dy + " px"
    : reading
      ? "均亮 " + reading.mean_luma.toFixed(2) + " · 偏亮 " + reading.bright + " · 偏暗 " + reading.dark
      : "截线在测量框外";
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/panelpatch" + route("/export/" + filename) + savedQuery();
  }
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/panelpatch" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null, pair: null, pairIndex: null, pairPhoto: null,
    pairOpen: false});
  get("library").value = card.id;
  show();
  paintPair();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  paintSource();
}

function paintPair() {
  const pair = state.pair;
  const list = get("pair-list");
  list.replaceChildren();
  const open = Boolean(pair && state.pairOpen && state.pairIndex !== null);
  get("pair-back").hidden = !open;
  for (const button of document.querySelectorAll("[data-mode], [data-chart]")) button.hidden = open;
  get("probe-form").hidden = open;
  get("probe-title").textContent = open ? "另一张原片实际配对点" : "原片点读";
  get("probe-result").hidden = open;
  get("pair-reading").hidden = !open;
  get("readout-title").textContent = open ? "另一张原图配对点偏差" : "当前列平均偏差";
  get("calibration").hidden = open;
  get("outputs-panel").hidden = open;
  get("profile-panel").hidden = open;
  if (open) {
    const entry = pair.pairs[state.pairIndex];
    get("pair-reading").textContent = "实际配对点 · " + pointLabel(entry.other);
  }
  get("pair-state").textContent = pair
    ? "已配 " + pair.summary.pairs + " 对 · 原Y差 ≤ " + pair.max_dy + " px"
    : "未配对";
  get("pair-dy").value = pair ? pair.max_dy : get("pair-dy").value;
  get("pair-summary").textContent = pair
    ? "当前卡 " + pair.primary.name + " 可配 " + pair.summary.primary.eligible + " 点 · 另一张 " +
      pair.other.name + " 可配 " + pair.summary.other.eligible + " 点；未配 " +
      pair.summary.primary.unpaired + " / " + pair.summary.other.unpaired + " 点。"
    : "沿两张卡已保存的竖截线，各用自己的参考与限值。";
  notice(pair?.warning || "", "pair-warning");
  const unpaired = pair ? pair.summary.primary.unpaired + pair.summary.other.unpaired : 0;
  get("pair-unpaired").hidden = !unpaired;
  get("pair-unpaired").textContent = unpaired
    ? "当前截线原位保留 " + pair.summary.primary.unpaired + " 个未配越限点，另一张保留 " +
      pair.summary.other.unpaired + " 个；通道为0或255的越限点标为 ×，不参与配对。"
    : "";
  if (!pair) return;
  for (const [index, entry] of pair.pairs.entries()) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "pair-row";
    button.setAttribute("aria-pressed", String(state.pairIndex === index));
    button.innerHTML = "<b>" + pairLabel(entry) + "</b><span>" + pointLabel(entry.primary) + "</span>";
    button.addEventListener("click", () => {
      if (state.pairIndex === index && state.pairOpen) return closePairView();
      state.pairIndex = index;
      action(openPairView);
    });
    item.append(button);
    list.append(item);
  }
  if (!pair.pairs.length) {
    const item = document.createElement("li");
    item.className = "pair-empty";
    item.textContent = "当前截线没有符合条件的一对越限点。";
    list.append(item);
  }
  const leftovers = pair.items.filter((item) => item.status !== "paired");
  for (const item of leftovers.slice(0, 40)) {
    const row = document.createElement("li");
    row.className = "pair-leftover";
    row.textContent = (item.status === "clipped" ? "不参与" : "未配") + " · " + pointLabel(item);
    list.append(row);
  }
  if (leftovers.length > 40) {
    const row = document.createElement("li");
    row.className = "pair-leftover";
    row.textContent = "另有 " + (leftovers.length - 40) + " 个未配或不参与的点保留在截线原位。";
    list.append(row);
  }
  if (state.card) show();
}

async function openPairView() {
  const pair = state.pair;
  if (!pair || state.pairIndex === null) return;
  if (!state.pairPhoto) {
    const photo = new Image();
    photo.src = "/panelpatch/cards/" + pair.other.id + "/capture.png";
    await photo.decode();
    state.pairPhoto = photo;
  }
  state.pairOpen = true;
  paintPair();
  paintSource();
  notice("");
  get("capture").scrollIntoView({behavior: "smooth", block: "center"});
}

function closePairView() {
  state.pairOpen = false;
  paintPair();
  paintSource();
}

function clearPair() {
  state.pair = null;
  state.pairIndex = null;
  state.pairPhoto = null;
  state.pairOpen = false;
  paintPair();
  if (state.card) show();
}

async function applyPair() {
  const other = get("pair-card").value;
  if (!other) throw new Error("请选择另一张试图卡。");
  const dy = Number(get("pair-dy").value);
  if (!Number.isInteger(dy) || dy < 0) throw new Error("原 Y 差上限必须是非负整数。");
  const pair = await api(route("/paired") + savedQuery() + "&other=" + encodeURIComponent(other) +
    "&max_dy=" + dy);
  Object.assign(state, {pair, pairIndex: null, pairPhoto: null, pairOpen: false});
  get("pair-card").value = other;
  paintPair();
  paintSource();
  notice(pair.warning ? "" : pair.summary.pairs
    ? "已配 " + pair.summary.pairs + " 对；点选一处匹配即可切到另一张卡读取实际配对点。"
    : "两张截线没有可配的越限点。");
}

get("practice").addEventListener("click", () => action(async () => {
  await open(await api("/practice", {method: "POST"}));
  await library();
}));

get("library").addEventListener("change", () => {
  if (get("library").value) action(async () => open(await api("/cards/" + get("library").value)));
});
get("open-import").addEventListener("click", () => {
  notice("", "import-notice");
  get("import").showModal();
});
get("cancel-import").addEventListener("click", () => get("import").close());
get("upload").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const card = await api("/cards", {method: "POST", body: new FormData(event.target)});
    await open(card);
    await library();
    get("import").close();
    event.target.reset();
  }, "import-notice");
});
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.mode = button.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
}));
get("capture").addEventListener("click", (event) => {
  if (!state.card || state.pairOpen) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width)));
  const y = Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)));
  action(async () => {
    await probe(x, y);
    if (state.mode === "mark") {
      settings.find((field) => field.dataset.setting === "focus").value = x;
      notice("已填入实际原片截线。");
    }
    if (state.mode === "reference") {
      settings.find((field) => field.dataset.setting === "ref_x").value = x;
      settings.find((field) => field.dataset.setting === "ref_y").value = y;
      notice("已填入实际原片参考点。");
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(settings.map((field) => [field.dataset.setting, Number(field.value)]));
    const card = await api(route(""), {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revision: state.card.revision, name: get("name").value, settings: fields}),
    });
    await open(card);
    await library();
  });
});
get("pair-apply").addEventListener("click", () => action(applyPair));
get("pair-clear").addEventListener("click", () => {
  clearPair();
  notice("");
});
get("pair-back").addEventListener("click", closePairView);
get("pair-card").addEventListener("change", () => {
  if (state.pair && get("pair-card").value !== state.pair.other.id) clearPair();
});
get("prepare").addEventListener("click", () => action(async () => {
  const {url} = await api(route("/prepare") + savedQuery(), {method: "POST"});
  location.assign(url);
}));
document.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
  state.chart = button.dataset.chart;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
  if (state.card) paintChart();
}));
action(library);
