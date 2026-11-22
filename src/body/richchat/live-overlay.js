'use strict';
(() => {
  const caption=document.getElementById('caption');
  async function update(){
    try{
      const response=await fetch('api/live/state',{cache:'no-store',credentials:'same-origin'});
      if(!response.ok)throw Error('status_offline');
      const state=await response.json();
      const fresh=Number(state.server_time)>0 && Date.now()/1000-Number(state.server_time)<6;
      // Subtitles follow actual TTS audio_start, NOT model generation or HTTP queue ACK.
      const text=(fresh && state.active && state.audio_speaking) ? String(state.caption||'').slice(0,360) : '';
      caption.textContent=text;caption.hidden=!text;
    }catch(_){caption.hidden=true;caption.textContent='';}
  }
  update();window.setInterval(update,550);
})();
