// Payroll Argentina - interacción mínima, sin dependencias.
// HTMX se ocupa de filtros y acciones; este archivo sólo gestiona el menú
// lateral en pantallas pequeñas.

(function () {
  "use strict";

  var body = document.body;
  var toggle = document.querySelector("[data-sidebar-toggle]");
  var backdrop = document.querySelector("[data-sidebar-close]");
  var sidebar = document.getElementById("app-sidebar");

  function setSidebar(open) {
    var wasOpen = body.classList.contains("sidebar-open");
    body.classList.toggle("sidebar-open", open);
    if (toggle) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Cerrar menú de navegación" : "Abrir menú de navegación");
    }
    if (sidebar) {
      sidebar.classList.toggle("is-open", open);
    }
    if (wasOpen && !open && toggle && window.matchMedia("(max-width: 991px)").matches) {
      toggle.focus();
    }
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      setSidebar(!body.classList.contains("sidebar-open"));
    });
  }

  if (backdrop) {
    backdrop.addEventListener("click", function () {
      setSidebar(false);
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      setSidebar(false);
    }
  });

  if (sidebar) {
    sidebar.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.matchMedia("(max-width: 991px)").matches) {
          setSidebar(false);
        }
      });
    });
  }

  // Cierra el menú si se pasa a escritorio.
  var desktop = window.matchMedia("(min-width: 992px)");
  function handleDesktopChange(event) {
    if (event.matches) {
      setSidebar(false);
    }
  }
  if (desktop.addEventListener) {
    desktop.addEventListener("change", handleDesktopChange);
  } else if (desktop.addListener) {
    desktop.addListener(handleDesktopChange);
  }
})();
