const HELP_META = {
  version: "Config Version 3",
  lastUpdated: "2026-07-25",
};

const topicSections = [...document.querySelectorAll(".topic")];
const tocLinks = [...document.querySelectorAll(".toc a")];
const searchInput = document.getElementById("topic-search");
const backToTopButton = document.getElementById("back-to-top");
const prevButton = document.getElementById("prev-topic");
const nextButton = document.getElementById("next-topic");

function setFooterMeta() {
  document.getElementById("footer-version").textContent = `ToolBar2 ${HELP_META.version}`;
  document.getElementById("footer-updated").textContent = `Last Updated ${HELP_META.lastUpdated}`;
}

function clearHighlights(element) {
  element.querySelectorAll("[data-original-html]").forEach((node) => {
    node.innerHTML = node.getAttribute("data-original-html") || "";
    node.removeAttribute("data-original-html");
  });
}

function applyHighlights(element, term) {
  if (!term) {
    clearHighlights(element);
    return;
  }
  const regex = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig");
  element.querySelectorAll("p, h3, h4, li, span, code").forEach((node) => {
    if (!node.hasAttribute("data-original-html")) {
      node.setAttribute("data-original-html", node.innerHTML);
    }
    const original = node.getAttribute("data-original-html") || "";
    node.innerHTML = original.replace(regex, "<mark>$1</mark>");
  });
}

function filterTopics() {
  const term = searchInput.value.trim().toLowerCase();
  topicSections.forEach((section) => {
    const details = section.querySelector("details");
    const haystack = `${section.dataset.title || ""} ${section.dataset.keywords || ""} ${section.textContent || ""}`.toLowerCase();
    const visible = !term || haystack.includes(term);
    section.hidden = !visible;
    if (visible && details && term) {
      details.open = true;
    }
    clearHighlights(section);
    if (visible && term) {
      applyHighlights(section, term);
    }
  });
  tocLinks.forEach((link) => {
    const target = document.querySelector(link.getAttribute("href"));
    link.hidden = !!target?.hidden;
  });
  updatePager();
}

function visibleTopics() {
  return topicSections.filter((section) => !section.hidden);
}

function activeTopicIndex() {
  const visible = visibleTopics();
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  visible.forEach((section, index) => {
    const distance = Math.abs(section.getBoundingClientRect().top - 120);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return { visible, index: bestIndex };
}

function updateTocActive() {
  const { visible, index } = activeTopicIndex();
  const activeId = visible[index]?.id || "";
  tocLinks.forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === `#${activeId}`);
  });
}

function updatePager() {
  const { visible, index } = activeTopicIndex();
  const prev = visible[index - 1];
  const next = visible[index + 1];
  prevButton.disabled = !prev;
  nextButton.disabled = !next;
  prevButton.dataset.target = prev ? prev.id : "";
  nextButton.dataset.target = next ? next.id : "";
}

function navigateToButtonTarget(button) {
  const id = button.dataset.target;
  if (!id) {
    return;
  }
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

searchInput.addEventListener("input", filterTopics);
prevButton.addEventListener("click", () => navigateToButtonTarget(prevButton));
nextButton.addEventListener("click", () => navigateToButtonTarget(nextButton));

window.addEventListener("scroll", () => {
  backToTopButton.classList.toggle("visible", window.scrollY > 320);
  updateTocActive();
  updatePager();
});

backToTopButton.addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: "smooth" });
});

tocLinks.forEach((link) => {
  link.addEventListener("click", () => {
    const target = document.querySelector(link.getAttribute("href"));
    target?.querySelector("details")?.setAttribute("open", "");
  });
});

setFooterMeta();
filterTopics();
updateTocActive();
updatePager();
