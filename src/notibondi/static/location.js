navigator.geolocation.getCurrentPosition(
  (position) => {
    htmx.ajax("GET", "/api/v1/stops/nearby", {
      target: "#stops",
      values: { lat: position.coords.latitude, lon: position.coords.longitude },
    });
  },
  (error) => console.log("geolocation error", error.code, error.message),
  { timeout: 10000, maximumAge: 60000 },
);
