// Small things every page needs: closing the menu, and opening and closing
// a stop's arrivals.

const menu = document.querySelector(".menu");

// <details> only closes from its own button; also close it from outside
document.addEventListener("click", (event) => {
  if (menu.open && !menu.contains(event.target)) menu.open = false;
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && menu.open) {
    menu.open = false;
    menu.querySelector("summary").focus();
  }
});

// A stop's button loads its arrivals with htmx. Tapping it again used to
// reload them; now it closes them. This runs in the capture phase, before
// htmx's own listener on the button, so a close never sends a request.
document.addEventListener(
  "click",
  (event) => {
    const button = event.target.closest(".stop[aria-expanded]");
    if (!button) return;
    const open = button.getAttribute("aria-expanded") === "true";
    const li = button.closest("li");
    if (open) {
      event.stopPropagation();
      // Removing the arrivals also stops their refresh every 30 s
      li.querySelector(".arrivals-slot").replaceChildren();
    }
    button.setAttribute("aria-expanded", String(!open));
    // For the stops map, which highlights the open stop
    li.dispatchEvent(new CustomEvent("stop-toggle", { bubbles: true, detail: { open: !open } }));
  },
  { capture: true },
);

// A stop's panel (#detail, in base.html), over the page you are on. It has
// its own address, /stops/{id}, so it can be shared and Back closes it.
// Not htmx's hx-push-url: on Back, htmx puts back a copy of the page's HTML,
// and a copy of the stops map is a dead picture.
const detail = document.getElementById("detail");
// Where the panel was opened from, to give the focus back when it closes
let opener = null;

function showDetail() {
  detail.hidden = false;
  detail.querySelector("#detail-title")?.focus();
}

function hideDetail() {
  detail.hidden = true;
  // Removing it also stops its arrivals' refresh every 30 s
  detail.replaceChildren();
  opener?.focus();
  opener = null;
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("a.open-detail[data-detail]");
  // A new tab (ctrl, middle click) follows the real link
  if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
  event.preventDefault();
  opener = link;
  htmx.ajax("GET", link.dataset.detail, { target: detail }).then(showDetail);
  const url = link.getAttribute("href");
  // From one panel to another, replace it: Back goes to the page, not the
  // panel before
  if (history.state?.detail) history.replaceState({ detail: url }, "", url);
  else history.pushState({ detail: url }, "", url);
});

function closeDetail() {
  if (history.state?.detail) {
    // We opened it: Back closes it (popstate below)
    history.back();
  } else {
    // It came with the page (/stops/{id}): under it is the stops page
    history.replaceState(null, "", "/stops");
    hideDetail();
  }
}

document.addEventListener("click", (event) => {
  if (event.target.closest(".detail-close")) closeDetail();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !detail.hidden && !menu.open) closeDetail();
});
window.addEventListener("popstate", () => {
  if (!detail.hidden && !location.pathname.startsWith("/stops/")) hideDetail();
});

// "Actualizado hace X s": how old the arrivals in the panel are. They
// refresh every 30 s; a stale number means the connection is gone.
let updatedAt = null;
detail.addEventListener("htmx:afterSwap", () => {
  updatedAt = Date.now();
  tick();
});
function tick() {
  const label = detail.querySelector(".updated");
  if (!label || updatedAt === null) return;
  const seconds = Math.round((Date.now() - updatedAt) / 1000);
  label.textContent = seconds < 5 ? "Actualizado recién" : `Actualizado hace ${seconds} s`;
}
setInterval(tick, 5000);
