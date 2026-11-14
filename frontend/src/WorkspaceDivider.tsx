import {useRef, useState} from "react";

export default function WorkspaceDivider({value,onChange}:{value:number;onChange:(value:number)=>void}) {
  const pointer = useRef<number|null>(null);
  const [dragging,setDragging] = useState(false);
  const clamp = (next:number) => Math.max(20,Math.min(70,next));
  return <div className={`workspace-divider ${dragging?"dragging":""}`}
    role="separator" aria-label="Resize instructions and editor" aria-orientation="vertical"
    aria-valuemin={20} aria-valuemax={70} aria-valuenow={Math.round(value)}
    aria-valuetext={`${Math.round(value)} percent instructions`} tabIndex={0}
    title="Drag to resize · Arrow keys to adjust · Double-click to reset"
    onPointerDown={event=>{
      if(event.button!==0)return;
      pointer.current=event.pointerId;
      event.currentTarget.setPointerCapture(event.pointerId);
      setDragging(true);
      event.preventDefault();
    }}
    onPointerMove={event=>{
      if(pointer.current!==event.pointerId)return;
      const bounds=event.currentTarget.parentElement!.getBoundingClientRect();
      onChange(clamp((event.clientX-bounds.left)/bounds.width*100));
    }}
    onPointerUp={event=>{
      if(pointer.current!==event.pointerId)return;
      pointer.current=null;setDragging(false);
      event.currentTarget.releasePointerCapture(event.pointerId);
    }}
    onLostPointerCapture={()=>{pointer.current=null;setDragging(false)}}
    onPointerCancel={()=>{pointer.current=null;setDragging(false)}}
    onDoubleClick={()=>onChange(34)}
    onKeyDown={event=>{
      const next=event.key==="ArrowLeft"?value-2:event.key==="ArrowRight"?value+2:
        event.key==="Home"?20:event.key==="End"?70:undefined;
      if(next!==undefined){event.preventDefault();onChange(clamp(next))}
    }}><span/></div>;
}
