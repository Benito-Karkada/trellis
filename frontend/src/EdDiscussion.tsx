import {useEffect,useState} from "react";
import {MessageCircle} from "lucide-react";
import {api} from "./api";

export function EdDiscussionSettings() {
  const [url,setUrl]=useState("");const [loading,setLoading]=useState(true);const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [notice,setNotice]=useState("");
  useEffect(()=>{let live=true;api("settings/ed-discussion/").then(data=>{if(live)setUrl(data.url);}).catch(error=>{if(live)setError(error.message);}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[]);
  if(loading)return <p role="status">Loading integrations…</p>;
  return <section className="settings-card ed-settings"><div className="card-title"><div><h2>Ed Discussion</h2><p>Choose the course used by the Trellis browser extension for exercise questions.</p></div><MessageCircle/></div>
    <form onSubmit={async event=>{event.preventDefault();setBusy(true);setError("");setNotice("");try{const saved=await api("settings/ed-discussion/save/",{url});setUrl(saved.url);setNotice(saved.url?"Ed Discussion connected.":"Ed Discussion disconnected.");}catch(error){setError((error as Error).message);}finally{setBusy(false);}}}>
      <label>Ed Discussion course URL<input type="url" placeholder="https://edstem.org/us/courses/123/discussion" value={url} disabled={busy} onChange={event=>setUrl(event.target.value)}/></label>
      <p>The extension works on regular exercises and sandboxes. Programming quizzes are excluded. Clear the URL to disconnect.</p>
      {error&&<p role="alert" className="notification error">{error}</p>}{notice&&<p role="status">{notice}</p>}
      <button className="primary" disabled={busy}>{busy?"Saving…":"Save Ed settings"}</button>
    </form>
  </section>;
}
