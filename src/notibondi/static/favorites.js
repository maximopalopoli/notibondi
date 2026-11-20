// Favorite stops and lines, kept in this browser: there are no accounts.
// Every stop list has a ☆ button per stop, and the lines map one per
// direction of each branch; this marks them and saves the changes.
// The favorites are kept in the user's order: a new one goes first, and
// /favorites moves them with ↑ and ↓.
// A stop is its id; a line is its name and direction_id: "108A:1".

const Favorites = (() => {
  const STOPS = "notibondi.favorites";
  const LINES = "notibondi.favoriteLines";

  // localStorage can throw (private windows, blocked site data) or hold
  // something else: then there are just no favorites
  function read(key) {
    try {
      const values = JSON.parse(localStorage.getItem(key));
      return Array.isArray(values) ? values.filter((v) => typeof v === "string") : [];
    } catch {
      return [];
    }
  }

  function save(key, values) {
    try {
      localStorage.setItem(key, JSON.stringify(values));
    } catch {}
  }

  function toggle(key, value) {
    const values = read(key).filter((other) => other !== value);
    const adding = values.length === read(key).length;
    save(key, adding ? [value, ...values] : values);
    return adding;
  }

  // One place up (-1) or down (1); at either end it stays
  function move(key, value, by) {
    const values = read(key);
    const from = values.indexOf(value);
    const to = from + by;
    if (from < 0 || to < 0 || to >= values.length) return;
    [values[from], values[to]] = [values[to], values[from]];
    save(key, values);
  }

  // What a star button stands for: [where it's kept, its value]
  function favoriteOf(button) {
    if (button.dataset.stopId) return [STOPS, button.dataset.stopId];
    return [LINES, `${button.dataset.line}:${button.dataset.direction}`];
  }

  // Only the star changes: a line's button also says where it goes
  function mark(button, on) {
    button.setAttribute("aria-pressed", on);
    button.textContent = (on ? "★" : "☆") + button.textContent.slice(1);
  }

  const BUTTONS = ".fav[data-stop-id], .fav[data-line][data-direction]";
  // A favorite on /favorites, and its own star: the first one in it (the
  // arrivals inside have stars of their own, after it)
  const ITEM = "[data-all] > ul > li";
  const starOf = (item) => item.querySelector(BUTTONS);

  function markAll(root = document) {
    const saved = { [STOPS]: new Set(read(STOPS)), [LINES]: new Set(read(LINES)) };
    for (const button of root.querySelectorAll(BUTTONS)) {
      const [key, value] = favoriteOf(button);
      mark(button, saved[key].has(value));
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest(BUTTONS);
    if (button) {
      const on = toggle(...favoriteOf(button));
      // Another star of the same stop or line on the page says the same
      markAll();
      // On /favorites, a favorite you take out leaves the list
      const item = button.closest(ITEM);
      if (!on && item && starOf(item) === button) item.remove();
      return;
    }
    const arrow = event.target.closest("[data-move]");
    const item = arrow?.closest(ITEM);
    if (!item) return;
    const by = Number(arrow.dataset.move);
    move(...favoriteOf(starOf(item)), by);
    const other = by < 0 ? item.previousElementSibling : item.nextElementSibling;
    if (other) by < 0 ? other.before(item) : other.after(item);
    arrow.focus();
  });
  // Lists come with htmx, after the page loaded
  document.body.addEventListener("htmx:afterSwap", (event) => markAll(event.detail.target));
  markAll();

  return { list: () => read(STOPS), lines: () => read(LINES) };
})();
