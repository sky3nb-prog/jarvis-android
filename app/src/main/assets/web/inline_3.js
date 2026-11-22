(function(){ // Nur-Kugel-Modus im Fokus: Text, Gesprächsknopf und Schreibfeld gleiten nach unten weg
  var b=document.getElementById("cleanbtn"); if(!b) return;
  function set(on){ document.body.classList.toggle("clean",on); b.classList.toggle("on",on); try{localStorage.setItem("hud_clean",on?"1":"")}catch(e){} }
  try{ set(localStorage.getItem("hud_clean")==="1") }catch(e){}
  b.addEventListener("click",function(e){ e.stopPropagation(); set(!document.body.classList.contains("clean")) });
})();
