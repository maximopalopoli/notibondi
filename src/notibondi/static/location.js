const MESSAGES = {
  1: "No diste permiso para usar tu ubicación.",       // PERMISSION_DENIED
  2: "No pudimos saber dónde estás.",                   // POSITION_UNAVAILABLE
  3: "Tardó demasiado en obtener tu ubicación.",        // TIMEOUT
};

function showError(target, message) {
  const p = document.createElement("p");
  p.className = "error";
  p.setAttribute("role", "alert");
  p.textContent = message;
  target.replaceChildren(p);
}

// Without the location, searching by name is the other way to find a stop
function locationFailed(message) {
  showError(
    document.querySelector("#stops"),
    `${message} Podés buscar una parada por nombre.`,
  );
  document.querySelector("#search").focus();
}

document.body.addEventListener("htmx:responseError", (event) => {
  showError(event.detail.target, "Hubo un problema en el servidor. Probá de nuevo en un rato.");
});
document.body.addEventListener("htmx:sendError", (event) => {
  showError(event.detail.target, "No hay conexión. Revisá tu internet y probá de nuevo.");
});

if (!navigator.geolocation) {
  locationFailed("Tu navegador no permite usar la ubicación.");
} else {
  navigator.geolocation.getCurrentPosition(
    (position) => {
      htmx.ajax("GET", "/partials/stops/nearby", {
        target: "#stops",
        values: { lat: position.coords.latitude, lon: position.coords.longitude },
      });
    },
    (error) => locationFailed(MESSAGES[error.code]),
    { timeout: 10000, maximumAge: 60000 },
  );
}

