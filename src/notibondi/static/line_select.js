// "Seleccioná la línea" in two steps, in the same select: first the range
// (1 a 99, 100 a 199…), then the numbers in it. 274 numbers in one list is
// a lot of scrolling on a phone.
//
// The page sends every number inside <optgroup>s, so without this script
// the select still works as one long list.

const select = document.getElementById("line-select");

const groups = [...select.querySelectorAll("optgroup")].map((group) => ({
  label: group.label,
  names: [...group.querySelectorAll("option")].map((option) => option.value),
}));

function option(value, text) {
  const element = document.createElement("option");
  element.value = value;
  element.textContent = text;
  return element;
}

function showRanges() {
  select.replaceChildren(
    option("", "Elegí un rango…"),
    ...groups.map((group, i) =>
      option(`range:${i}`, `${group.label} (${group.names.length})`),
    ),
  );
  select.value = "";
}

function showNumbers(i) {
  const group = groups[i];
  select.replaceChildren(
    option("", `Elegí la línea (${group.label})…`),
    option("back:", "← Otros rangos"),
    ...group.names.map((name) => option(name, name)),
  );
  select.value = "";
}

// Opens the list again for the next step. Only Chromium (Brave, Chrome)
// does it for a select; elsewhere it throws, and a second tap opens it.
function reopen() {
  try {
    select.showPicker();
  } catch {}
}

select.addEventListener("change", () => {
  const value = select.value;
  if (value.startsWith("range:")) {
    showNumbers(Number(value.slice("range:".length)));
    reopen();
  } else if (value === "back:") {
    showRanges();
    reopen();
  }
  // A line name: htmx loads its branches, and the numbers stay in the list
});

showRanges();
