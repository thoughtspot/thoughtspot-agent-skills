
(function () {
  var root = document.documentElement, btn = document.getElementById("theme");
  try { var t = localStorage.getItem("report-theme"); if (t) root.setAttribute("data-theme", t); } catch (e) {}
  btn.addEventListener("click", function () {
    var dark = root.getAttribute("data-theme") === "dark" ||
      (!root.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
    var next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("report-theme", next); } catch (e) {}
  });
  window.addEventListener("beforeprint", function () {
    document.querySelectorAll("details").forEach(function (d) { d.setAttribute("open", ""); });
  });
})();
