(function(){try{const es=new EventSource("/events");es.onmessage=(e)=>{try{const m=JSON.parse(e.data);if(m.type==="skill"&&window.JSkill)JSkill.show(m.data||{});}catch(x){}};}catch(e){}})();
