async function api(action) {
  const res = await fetch("/api/" + action, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return res.json();
}

function setMsg(text) {
  document.getElementById("msg").textContent = text || "";
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const SECTION_META = {
  global_ai: { label: "全球 AI 动态", tags: "Agent · 治理 · 产业" },
  legal_ai: { label: "法律 AI / 法律科技", tags: "工具 · 案例 · 落地" },
  two_institute: { label: "两院法务", tags: "合规 · 监管 · 教育科研" },
};

function renderBriefing(text) {
  const el = document.getElementById("briefing");
  if (!text) {
    el.textContent = "尚未生成。";
    return;
  }
  el.innerHTML = escapeHtml(text)
    .replace(/\n{2,}/g, "<br/><br/>")
    .replace(/\n/g, "<br/>");
}

function categoryOf(it) {
  const tags = (it.tags || []).filter((t) => t && t !== "未分类").slice(0, 2);
  const scenes = (it.impact_scenes || []).slice(0, 2);
  const parts = tags.length ? tags : scenes.length ? scenes : ["资讯"];
  return parts.join(" | ");
}

function renderCard(it) {
  const date = (it.published_date || (it.published_at || "").slice(0, 10) || "").replace(/-/g, ".") || "—";
  const title = escapeHtml(it.title || "（无标题）");
  const titleHtml = it.url
    ? `<a href="${escapeHtml(it.url)}" target="_blank" rel="noopener">${title}</a>`
    : title;
  const scenes = (it.impact_scene_tags || (it.impact_scenes || []).map((s) => "#" + s)).join(" ") || "—";
  let keyInfo = String(it.key_info || it.summary || it.title || "—")
    .replace(/日期[：:]\s*\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[^\n]*/g, " ")
    .replace(/来源[：:]\s*[^\n]{0,40}/g, " ")
    .replace(/分享[：:]\s*\S*/g, " ")
    .replace(/\s+/g, " ")
    .trim() || "—";
  const legal = String(it.legal_focus || "").trim();
  const legalGeneric = !legal || legal.includes("需承办人判断是否与两院") || legal.includes("建议对照现行制度评估");
  const legalHtml = !legalGeneric
    ? `<p class="field"><strong>法务关注点：</strong>${escapeHtml(legal)}</p>`
    : "";
  return `
    <article class="news-row">
      <div class="news-thumb"></div>
      <div class="news-body">
        <div class="news-cat">${escapeHtml(categoryOf(it))}</div>
        <p class="field title-field"><strong>标题：</strong>${titleHtml}</p>
        <p class="field"><strong>日期：</strong>${escapeHtml(date)}</p>
        <p class="field"><strong>地区/主体：</strong>${escapeHtml(it.region || "—")}</p>
        <p class="field"><strong>来源：</strong>${escapeHtml(it.source || "—")}</p>
        <p class="field"><strong>延伸来源：</strong>${escapeHtml(it.extended_source || "—")}</p>
        <p class="field"><strong>关键信息：</strong>${escapeHtml(keyInfo)}</p>
        ${legalHtml}
        <p class="field"><strong>影响场景：</strong>${escapeHtml(scenes)}</p>
        ${it.url ? `<a class="detail-link" href="${escapeHtml(it.url)}" target="_blank" rel="noopener">详情 →</a>` : ""}
      </div>
    </article>`;
}

function renderSections(content) {
  const mount = document.getElementById("sectionBlocks");
  const sections = content.sections || {};
  const order = ["global_ai", "legal_ai", "two_institute"];
  let html = "";
  let total = 0;
  for (const key of order) {
    const meta = SECTION_META[key];
    const items = sections[key] || [];
    total += items.length;
    const cards = items.length
      ? items.map(renderCard).join("")
      : "<p class='empty'>本期本板块暂无精选</p>";
    html += `
      <section class="sec-block">
        <div class="sec-head">
          <h3>${escapeHtml(meta.label)}</h3>
          <span class="sec-tags">${escapeHtml(meta.tags)}</span>
        </div>
        <div class="sec-cards">${cards}</div>
      </section>`;
  }
  if (!total && (content.items || []).length) {
    html = `<section class="sec-block"><div class="sec-cards">${content.items.map(renderCard).join("")}</div></section>`;
  }
  mount.innerHTML = html;
}

function renderWeekClosing(content) {
  const el = document.getElementById("weekClosing");
  if (!el) return;
  let ref = (content.week_legal_reference || "").trim();
  if (!ref) {
    const q = (content.week_think_question || "").trim();
    const a = (content.week_action_suggestion || "").trim();
    if (q && a) ref = q.replace(/[？?]+$/, "") + "；" + a;
    else ref = q || a;
  }
  if (!ref) {
    const sections = content.sections || {};
    for (const key of ["global_ai", "legal_ai", "two_institute"]) {
      for (const it of sections[key] || []) {
        if (!ref && it.think_questions) ref = it.think_questions;
        if (!ref && it.action_suggestions) ref = it.action_suggestions;
        if (ref) break;
      }
      if (ref) break;
    }
  }
  if (!ref) {
    ref =
      "本期哪些变化可能在一个月内转化为两院的合同审核、制度修订或跨部门合规把关义务？" +
      "法务部应优先跟进相关边界，并牵头梳理需修订的条款清单与会签要点。";
  }
  ref = ref.replace(/【[^】]*】/g, "").replace(/^法务视角[：·\s]*/, "").trim();
  el.innerHTML = `<p class="closing-line"><strong>法务部参考建议：</strong>${escapeHtml(ref)}</p>`;
}

function renderContent(content) {
  if (!content) return;
  document.getElementById("contentTitle").textContent = content.title || "本期周报";
  renderBriefing(content.mainline || content.briefing || "");
  renderSections(content);
  renderWeekClosing(content);
}

function setLights(data) {
  document.getElementById("statusLine").textContent = "已连接";
  document.getElementById("logs").textContent = (data.logs || []).join("\n") || "";
  if (data.content) renderContent(data.content);
}

async function refresh() {
  try {
    const data = await api("status");
    setLights(data);
  } catch (e) {
    document.getElementById("statusLine").textContent = "未连接";
  }
}

async function onAction(action) {
  if (action === "reset_store") {
    const ok = window.confirm("确定清空采集记录？");
    if (!ok) return;
  }
  const page = document.querySelector(".page");
  page.classList.add("busy");
  setMsg("处理中…");
  try {
    const data = await api(action);
    // 只保留短状态，不展示待审/文件名等说明
    const clean = String(data.msg || "")
      .replace(/[。.]?可推送.*?条。?/g, "")
      .replace(/[。.]?待审.*?条。?/g, "")
      .replace(/[。.]?本批.*?条。?/g, "")
      .replace(/（已用.*?）/g, "")
      .trim();
    setMsg(clean || (data.ok ? "完成" : "失败"));
    if (data.content) renderContent(data.content);
    await refresh();
    if ((action === "run_digest" || action === "run_flash" || action === "run_quarterly") && data.ok) {
      document.querySelector(".content-box").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (e) {
    setMsg("请求失败");
  } finally {
    page.classList.remove("busy");
  }
}

document.querySelectorAll("[data-action]").forEach((btn) => {
  btn.addEventListener("click", () => onAction(btn.getAttribute("data-action")));
});

refresh();
setInterval(refresh, 8000);
