import {useEffect,useRef,useState} from "react";
import {createPortal} from "react-dom";
import {LogOut,X} from "lucide-react";

export default function LogoutButton({onConfirm}:{onConfirm:()=>void|Promise<void>}) {
 const [open,setOpen]=useState(false),[busy,setBusy]=useState(false);
 const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
 useEffect(()=>{if(open)dialog.current?.showModal();},[open]);
 function close(){if(busy)return;dialog.current?.close();setOpen(false);trigger.current?.focus();}
 return <><button ref={trigger} className="logout-button" onClick={()=>setOpen(true)}><LogOut size={17}/>Logout</button>
 {open&&createPortal(<dialog ref={dialog} className="logout-dialog" aria-labelledby="logout-title" onCancel={event=>{event.preventDefault();close();}}>
  <div className="logout-dialog-heading"><span className="logout-symbol"><LogOut size={24}/></span><button aria-label="Close logout confirmation" disabled={busy} onClick={close}><X size={20}/></button></div>
  <h2 id="logout-title">Log out of Trellis?</h2><p>Your saved work will be here when you return. Any unsaved edits will be lost.</p>
  <div className="logout-dialog-actions"><button autoFocus disabled={busy} onClick={close}>Stay here</button><button className="primary" disabled={busy} onClick={async()=>{setBusy(true);try{await onConfirm();}finally{setBusy(false);setOpen(false);}}}>{busy?"Logging out…":"Log out"}</button></div>
 </dialog>,document.body)}</>;
}
