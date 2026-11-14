import BrandLogo from "./BrandLogo";
import {useState} from "react";
import {ArrowRight,BookOpen,CheckCircle2} from "lucide-react";
import {api} from "./api";

export default function AuthScreen({onAuthenticated,localLogin,registrationOpen}:{onAuthenticated:()=>void;localLogin:boolean;registrationOpen:boolean}){
 const [mode,setMode]=useState<"login"|"register">("login"),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const [email,setEmail]=useState(""),[password,setPassword]=useState(""),[firstName,setFirstName]=useState(""),[lastName,setLastName]=useState("");
 async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setError("");try{await api(mode==="login"?"auth/login/":"auth/register/",{email,password,first_name:firstName,last_name:lastName});onAuthenticated()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <main className="auth-shell">

  <section className="auth-story"><a className="brand" href="/"><BrandLogo large/></a><div className="auth-story-body"><span className="auth-kicker">TRELLIS</span><h1>Your course work,<br/>all in one place.</h1><p>Read lessons, work through problems, and practice without leaving the course.</p><div className="auth-feature"><CheckCircle2/><span><strong>Keep your place</strong>Progress and workspaces are saved automatically.</span></div><div className="auth-feature"><BookOpen/><span><strong>Learn and practice together</strong>Lessons, videos, feedback, and coding tools stay connected.</span></div></div></section>
  <section className="auth-panel"><form className="auth-card" onSubmit={submit}><h2>{mode==="login"?"Welcome back":"Join Trellis"}</h2><p>{mode==="login"?"Enter the email connected to your course.":"Create your account with your course email."}</p>{mode==="register"&&<div className="form-row"><label>First name<input autoComplete="given-name" value={firstName} onChange={e=>setFirstName(e.target.value)} required/></label><label>Last name<input autoComplete="family-name" value={lastName} onChange={e=>setLastName(e.target.value)} required/></label></div>}<label>Email<input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} required/></label><label>Password<input type="password" autoComplete={mode==="login"?"current-password":"new-password"} value={password} onChange={e=>setPassword(e.target.value)} minLength={8} required/></label>{error&&<div className="auth-error">{error}</div>}<button className="primary auth-submit" disabled={busy}>{busy?"Please wait…":mode==="login"?"Sign in":"Create account"}<ArrowRight size={17}/></button>{localLogin&&<button type="button" className="local-workspace" onClick={()=>api("local-login/",{}).then(onAuthenticated).catch(e=>setError(e.message))}>Open local instructor workspace</button>}</form></section>
 </main>
}
