const MESSAGES = {
  1: "No diste permiso para usar tu ubicación.",       // PERMISSION_DENIED
  2: "No pudimos saber dónde estás.",                   // POSITION_UNAVAILABLE
  3: "Tardó demasiado en obtener tu ubicación.",        // TIMEOUT
};
// The browser's own timeout only starts after the permission prompt is
// answered, so an ignored prompt (or Brave on a desktop, which often never
// finds a position) would show "Buscando…" forever without this one
const SLOW_LOCATION_MS = 5000;
const SAVED_ADDRESS = "notibondi.address";

const stops = document.querySelector("#stops");
const addressForm = document.querySelector("#address-form");
const addressInput = document.querySelector("#address");

// Once the user picks an address, a late location must not replace it
let usedAddress = false;
let fellBack = false;

// localStorage can throw (private windows, blocked site data): it's only a
// convenience, so the page works the same without it
function savedAddress() {
  try {
    return localStorage.getItem(SAVED_ADDRESS);
  } catch {
    return null;
  }
}

function saveAddress(q) {
  try {
    localStorage.setItem(SAVED_ADDRESS, q);
  } catch {}
}

function showError(target, message) {
  const p = document.createElement("p");
  p.className = "error";
  p.setAttribute("role", "alert");
  p.textContent = message;
  target.replaceChildren(p);
}

function searchAddress(q) {
  usedAddress = true;
  addressInput.value = q;
  htmx.ajax("GET", "/partials/stops/address", { target: "#stops", values: { q } });
}

// Without the location, the address is the other way to say where you are
function locationFailed(message) {
  if (usedAddress || fellBack) return;
  fellBack = true;
  const saved = savedAddress();
  if (saved) {
    searchAddress(saved);
    return;
  }
  showError(stops, `${message} Escribí tu dirección arriba.`);
  addressInput.focus();
}

addressForm.addEventListener("submit", () => {
  usedAddress = true;
});

// Remember an address only once it found stops, not a typo
document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target === stops && stops.querySelector(".place")) {
    saveAddress(addressInput.value.trim());
  }
});

document.body.addEventListener("htmx:responseError", (event) => {
  showError(event.detail.target, "Hubo un problema en el servidor. Probá de nuevo en un rato.");
});
document.body.addEventListener("htmx:sendError", (event) => {
  showError(event.detail.target, "No hay conexión. Revisá tu internet y probá de nuevo.");
});

if (!navigator.geolocation) {
  locationFailed("Tu navegador no permite usar la ubicación.");
} else {
  const slow = setTimeout(
    () => locationFailed("Tu ubicación está tardando."),
    SLOW_LOCATION_MS,
  );
  navigator.geolocation.getCurrentPosition(
    (position) => {
      clearTimeout(slow);
      if (usedAddress) return;
      htmx.ajax("GET", "/partials/stops/nearby", {
        target: "#stops",
        values: { lat: position.coords.latitude, lon: position.coords.longitude },
      });
    },
    (error) => {
      clearTimeout(slow);
      locationFailed(MESSAGES[error.code]);
    },
    { timeout: 10000, maximumAge: 60000 },
  );
}
