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

  // Alta de convenios: zonas de arrastre con la entrada nativa como
  // alternativa accesible. Valida extensión y tamaño, muestra el archivo
  // elegido y un indicador de progreso al enviar el análisis.
  var ALLOWED_SUFFIXES = [".pdf", ".txt", ".md", ".csv"];

  function dropzoneErrorId(input) {
    return input.id + "-error";
  }

  function showDropzoneError(input, message) {
    var notice = document.getElementById(dropzoneErrorId(input));
    if (!notice) {
      return;
    }
    if (!message) {
      notice.hidden = true;
      notice.textContent = "";
      return;
    }
    notice.hidden = false;
    notice.textContent = message;
  }

  function renderDropzoneFile(zone, file) {
    var chip = zone.querySelector("[data-dropzone-file]");
    if (!chip) {
      return;
    }
    if (!file) {
      chip.hidden = true;
      chip.textContent = "";
      return;
    }
    var sizeKb = Math.max(1, Math.round(file.size / 1024));
    var sizeLabel = sizeKb >= 1024
      ? (sizeKb / 1024).toFixed(1) + " MB"
      : sizeKb + " KB";
    chip.hidden = false;
    chip.textContent = file.name + " (" + sizeLabel + ")";
  }

  function validateDropzoneFile(input, file) {
    var name = (file.name || "").toLowerCase();
    var okSuffix = ALLOWED_SUFFIXES.some(function (suffix) {
      return name.slice(-suffix.length) === suffix;
    });
    if (!okSuffix) {
      return "Extensión no soportada. Adjunte PDF, TXT, MD o CSV.";
    }
    var maxMb = parseInt(input.getAttribute("data-max-mb") || "20", 10);
    if (file.size > maxMb * 1024 * 1024) {
      return "El archivo supera los " + maxMb + " MB.";
    }
    if (file.size === 0) {
      return "El archivo está vacío.";
    }
    return "";
  }

  function setDropzoneFile(zone, input, file) {
    var problem = validateDropzoneFile(input, file);
    if (problem) {
      input.value = "";
      renderDropzoneFile(zone, null);
      showDropzoneError(input, problem);
      return false;
    }
    showDropzoneError(input, "");
    renderDropzoneFile(zone, file);
    return true;
  }

  document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
    var targetId = zone.getAttribute("for");
    var input = targetId ? document.getElementById(targetId) : null;
    if (!input) {
      return;
    }

    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) {
        renderDropzoneFile(zone, null);
        showDropzoneError(input, "");
        return;
      }
      setDropzoneFile(zone, input, file);
    });

    ["dragenter", "dragover"].forEach(function (eventName) {
      zone.addEventListener(eventName, function (event) {
        event.preventDefault();
        zone.classList.add("dropzone--dragover");
      });
    });

    ["dragleave", "drop"].forEach(function (eventName) {
      zone.addEventListener(eventName, function (event) {
        event.preventDefault();
        zone.classList.remove("dropzone--dragover");
      });
    });

    zone.addEventListener("drop", function (event) {
      var files = event.dataTransfer && event.dataTransfer.files;
      if (!files || files.length === 0) {
        return;
      }
      if (typeof DataTransfer === "undefined") {
        showDropzoneError(input, "Tu navegador no admite arrastrar archivos: usá el selector de archivos.");
        return;
      }
      var transfer = new DataTransfer();
      transfer.items.add(files[0]);
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  var analyzeForm = document.querySelector('form[action$="/propuestas-ia/nuevo"]');
  if (analyzeForm) {
    analyzeForm.addEventListener("submit", function () {
      var button = analyzeForm.querySelector("[data-analyze-submit]");
      var progress = analyzeForm.querySelector("[data-analyze-progress]");
      if (progress) {
        progress.hidden = false;
      }
      if (button) {
        button.disabled = true;
        button.textContent = "Analizando…";
      }
    });
  }
})();
