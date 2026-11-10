const MESSAGES = {
  1: "No diste permiso para usar tu ubicación.",       // PERMISSION_DENIED
  2: "No pudimos saber dónde estás.",                   // POSITION_UNAVAILABLE
  3: "Tardó demasiado en obtener tu ubicación.",        // TIMEOUT
};

function showError(message) {
  const p = document.createElement("p");
  p.className = "error";
  p.setAttribute("role", "alert");
  p.textContent = message;
  document.querySelector("#stops").replaceChildren(p);
}

document.body.addEventListener("htmx:responseError", () => {
  showError("Hubo un problema en el servidor. Probá de nuevo en un rato.");
});
document.body.addEventListener("htmx:sendError", () => {
  showError("Hubo un problema en la conexión con el servidor. Probá de nuevo en un rato.");
});

if (!navigator.geolocation) {
  showError("Tu navegador no permite usar la ubicación.");
} else {
  navigator.geolocation.getCurrentPosition(
    (position) => {
      htmx.ajax("GET", "/partials/stops/nearby", {
        target: "#stops",
        values: { lat: position.coords.latitude, lon: position.coords.longitude },
      });
    },
    (error) => showError(MESSAGES[error.code]),
    { timeout: 10000, maximumAge: 60000 },
  );
}

