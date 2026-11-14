import {useState} from "react";
import {Copy,ShieldCheck} from "lucide-react";
import {api} from "./api";

export function HonorlockSettings({quiz,onSaved,busy}:{quiz:{id:number;exam_mode:boolean;honorlock_enabled?:boolean;honorlock_password_set?:boolean};onSaved:()=>Promise<void>;busy:boolean}) {
  const [enabled,setEnabled]=useState(!!quiz.honorlock_enabled);
  const [password,setPassword]=useState("");
  const [saving,setSaving]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const url=`${window.location.origin}/#/course?lesson=${quiz.id}&category=content`;
  async function copy(value:string){try{await navigator.clipboard.writeText(value);setMessage("Copied.");}catch{setError("Copy the field manually.");}}
  return <section className="honorlock-settings" aria-label="Honorlock quiz settings">
    <h4><ShieldCheck size={18}/>Honorlock</h4>
    <label className="exam-switch"><input type="checkbox" checked={enabled} disabled={busy||saving} onChange={e=>setEnabled(e.target.checked)}/><span>Require Honorlock unlock</span></label>
    <p>Enable exam mode first. Register a third-party assessment in Honorlock with platform name Trellis, this link, and the same unique quiz password.</p>
    <label>Direct exam URL<div className="honorlock-field"><input readOnly value={url}/><button type="button" aria-label="Copy direct exam URL" onClick={()=>copy(url)}><Copy size={17}/></button></div></label>
    <label>{quiz.honorlock_password_set?"Replace quiz password (leave blank to keep it)":"Quiz password"}<input type="text" autoComplete="off" spellCheck={false} value={password} onChange={e=>setPassword(e.target.value)} placeholder="Set a unique password for this quiz" maxLength={128}/></label>
    <div className="honorlock-buttons"><button type="button" disabled={saving||busy} onClick={()=>{const bytes=crypto.getRandomValues(new Uint8Array(24));setPassword(Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join(""));setMessage("");}}>Generate password</button><button type="button" disabled={!password} onClick={()=>copy(password)}>Copy password</button></div>
    <p>Copy the password into Honorlock before saving. Trellis stores only a hash and cannot show it again. Replacing it requires updating Honorlock too and requires existing sessions to unlock again without resetting their timers.</p>
    {error&&<p role="alert" className="notification error">{error}</p>}{message&&<p role="status">{message}</p>}
    <button className="primary" type="button" disabled={saving||busy} onClick={async()=>{setSaving(true);setError("");setMessage("");try{await api(`settings/quizzes/${quiz.id}/honorlock/`,{enabled,password});setPassword("");await onSaved();setMessage("Honorlock settings saved.");}catch(e){setError((e as Error).message);}finally{setSaving(false);}}}>{saving?"Saving…":"Save Honorlock settings"}</button>
  </section>;
}

export function QuizAccessGate({title,honorlock,resuming,busy,error,onBegin}:{title:string;honorlock:boolean;resuming:boolean;busy:boolean;error:string;onBegin:(password?:string)=>Promise<void>}) {
  return <div className="exam-gate" role="dialog" aria-modal="true" aria-labelledby="quiz-gate-title"><section><ShieldCheck size={32}/><h2 id="quiz-gate-title">{title}</h2>
    {honorlock?<><p>Launch this assessment from Honorlock in Canvas and complete its setup. Use <strong>Unlock assessment</strong> to fill the quiz password below.</p><p>{resuming?"Your quiz timer continues while you reconnect.":"Your quiz timer starts only after the quiz unlocks."}</p></>:<p>Starting this quiz opens the exam workspace and begins its timer, if one is set.</p>}
    <form onSubmit={event=>{event.preventDefault();const form=event.currentTarget;const password=new FormData(form).get("password");void onBegin(typeof password==="string"?password:undefined);}}>
      {honorlock&&<label htmlFor="quiz-access-password">Quiz password<input id="quiz-access-password" name="password" type="password" autoComplete="off" autoFocus required maxLength={128}/></label>}
      {error&&<p className="notification error" role="alert">{error}</p>}
      <button className="primary" disabled={busy} type="submit">{busy?"Opening…":honorlock?resuming?"Unlock and resume quiz":"Unlock and begin quiz":"Begin quiz"}</button>
    </form><p>You can Run and Submit each question repeatedly until time expires or you submit the entire quiz.</p>
  </section></div>;
}
