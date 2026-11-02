/* ── Hamburger ── */
var hamburger = $(".hamburger");
var sidebar = $(".sidebar");
if(hamburger && sidebar){
  hamburger.addEventListener("click",function(){
    sidebar.classList.toggle("open");
  });
  /* Close on link click (mobile) */
  sidebar.addEventListener("click",function(e){
    if(e.target.closest("a[data-route]") && window.innerWidth <= 768){
      sidebar.classList.remove("open");
    }
  });
}

/* ── Init ── */
buildSidebar();
buildFilterPills();
window.addEventListener("hashchange", onRoute);
onRoute();

