// Your favorites, on two pages. On the home page, your nearest favorite
// stop and line, already open with their arrivals (without a location,
// your first ones). On /favorites (the sections have data-all), all of
// them in your order, to move them around (favorites.js).

const SECTIONS = [
  {
    target: document.getElementById("favorite"),
    url: "/partials/stops/favorite",
    param: "ids",
    saved: Favorites.list(),
    none:
      "<p>Todavía no tenés paradas favoritas. Marcalas con ☆ en " +
      '<a href="/stops">Paradas cerca</a>.</p>',
  },
  {
    target: document.getElementById("favorite-line"),
    url: "/partials/lines/favorite",
    param: "lines",
    saved: Favorites.lines(),
    none:
      "<p>Todavía no tenés líneas favoritas. Marcalas con ☆ en " +
      '<a href="/routes">Mapa de líneas</a>, al elegir el ramal.</p>',
  },
];

function show(position) {
  for (const { target, url, param, saved } of SECTIONS) {
    if (saved.length === 0) continue;
    const values = { [param]: saved };
    if ("all" in target.dataset) values.all = true;
    if (position) {
      values.lat = position.coords.latitude;
      values.lon = position.coords.longitude;
    }
    htmx.ajax("GET", url, { target, values });
  }
}

for (const { target, saved, none } of SECTIONS) {
  if (saved.length === 0) target.innerHTML = none;
  // On the home page, open it right away: the arrivals are why you come
  // here. On afterSettle, not afterSwap: before it, htmx hasn't wired up
  // the new button yet, and the click would mark it open without asking
  // for the arrivals
  if (!("all" in target.dataset)) {
    target.addEventListener("htmx:afterSettle", (event) => {
      if (event.detail.target !== target) return;
      target.querySelector(".stop[aria-expanded='false']")?.click();
    });
  }
}

if (SECTIONS.some((section) => section.saved.length > 0)) {
  // Only once: a late location after the timeout must not ask again
  let asked = false;
  const once = (position) => {
    if (asked) return;
    asked = true;
    show(position);
  };
  // Brave on a desktop may never answer, as on "Paradas cerca"
  setTimeout(() => once(null), 5000);
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(once, () => once(null), {
      timeout: 5000,
      maximumAge: 300000,
    });
  } else {
    once(null);
  }
}
