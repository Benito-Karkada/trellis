import {useEffect,useRef} from "react";
import {csrfToken} from "./api";

// Focus loss is an observation, not evidence of what the student did elsewhere.
export function useFocusTracking(lessonId:number|null,partId:number|null,enabled:boolean){
 const currentPart=useRef(partId);currentPart.current=partId;
 useEffect(()=>{
  if(!enabled || !lessonId)return;
  const tabId=crypto.randomUUID();
  let away:{id:string;started:number;reason:"tab"|"window";hidden:boolean;partId:number|null}|null=null;
  let blurTimer:ReturnType<typeof setTimeout>|undefined;
  const send=(state:"away"|"hidden"|"back"|"end")=>{
   if(!away)return;
   void fetch(`/api/assignments/${lessonId}/focus/`,{method:"POST",credentials:"same-origin",keepalive:true,
    headers:{"Content-Type":"application/json","X-CSRFToken":csrfToken()},body:JSON.stringify({event_id:crypto.randomUUID(),episode_id:away.id,tab_id:tabId,state,reason:away.reason,
     part_id:away.partId,elapsed_ms:Math.min(86400000,Math.max(0,Math.round(performance.now()-away.started)))})}).catch(()=>{});
  };
  const begin=(reason:"tab"|"window")=>{if(!away){away={id:crypto.randomUUID(),started:performance.now(),reason,hidden:reason==="tab",partId:currentPart.current};send("away");}};
  const end=(state:"back"|"end"="back")=>{clearTimeout(blurTimer);if(away){send(state);away=null;}};
  const visibility=()=>{
   if(document.hidden){if(!away)begin("tab");else if(!away.hidden){away.hidden=true;send("hidden");}}
   else if(document.hasFocus())end();
  };
  const blur=()=>{clearTimeout(blurTimer);blurTimer=setTimeout(()=>{
   // Interacting with the embedded course video can focus its iframe.
   if(!document.hidden && document.activeElement?.tagName==="IFRAME")return;
   begin(document.hidden?"tab":"window");
  },80);};
  const focus=()=>{if(!document.hidden)end();};
  const pagehide=()=>end("end");
  document.addEventListener("visibilitychange",visibility);window.addEventListener("blur",blur);window.addEventListener("focus",focus);window.addEventListener("pagehide",pagehide);
  return()=>{end("end");document.removeEventListener("visibilitychange",visibility);window.removeEventListener("blur",blur);window.removeEventListener("focus",focus);window.removeEventListener("pagehide",pagehide);};
 },[lessonId,enabled]);
}
