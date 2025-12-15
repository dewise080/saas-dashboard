// Keep LeadWebsite admin tabs usable even if the Bootstrap tab plugin is missing.
// Jazzmin renders fieldsets as tabs; when JS fails only the first tab is visible.
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var navLinks = Array.prototype.slice.call(
      document.querySelectorAll("#jazzy-tabs a.nav-link")
    );
    var panes = Array.prototype.slice.call(
      document.querySelectorAll(".tab-content .tab-pane")
    );

    if (!navLinks.length || !panes.length) {
      return;
    }

    var hasBootstrapTab =
      window.jQuery &&
      window.jQuery.fn &&
      typeof window.jQuery.fn.tab === "function";

    // If the bootstrap tab plugin is missing, show everything so content is not hidden.
    if (!hasBootstrapTab) {
      navLinks.forEach(function (link) {
        link.classList.add("active");
      });
      panes.forEach(function (pane) {
        pane.classList.add("show", "active");
      });
      return;
    }

    // Ensure clicks always toggle the correct pane (some browsers drop the data attribute binding).
    navLinks.forEach(function (link) {
      if (!link.dataset.toggle && !link.dataset.bsToggle) {
        link.setAttribute("data-toggle", "pill");
      }

      link.addEventListener("click", function (event) {
        event.preventDefault();

        try {
          window.jQuery(link).tab("show");
        } catch (err) {
          // Manual fallback in case the plugin throws
          panes.forEach(function (pane) {
            pane.classList.remove("show", "active");
          });
          navLinks.forEach(function (nav) {
            nav.classList.remove("active");
          });

          var targetId = link.getAttribute("href");
          var targetPane = targetId ? document.querySelector(targetId) : null;
          if (targetPane) {
            targetPane.classList.add("show", "active");
          }
          link.classList.add("active");
        }
      });
    });
  });
})();
