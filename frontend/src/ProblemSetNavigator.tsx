import {Check,ArrowLeft,ArrowRight} from "lucide-react";
type Part={id:number;title:string;earned_points:string;maximum_points:string;status:string};
export default function ProblemSetNavigator({parts,active,busy,onNavigate}:{parts:Part[];active:number|null;busy:boolean;onNavigate:(id:number)=>Promise<void>}) {
 const full=(p:Part)=>Number(p.maximum_points)>0&&Number(p.earned_points)>=Number(p.maximum_points);
 const index=parts.findIndex(part=>part.id===active);
 return <nav className="pset-navigator" aria-label="Problem set questions"><div className="pset-nav-heading"><div><span className="section-kicker">PROBLEM SET</span><strong>{parts.filter(full).length} of {parts.length} completed</strong></div></div>
 <div className="pset-question-row"><div className="pset-bubbles">{parts.map((part,i)=><button key={part.id} disabled={busy} className={`pset-bubble ${full(part)?"complete":""} ${active===part.id?"active":""}`} aria-current={active===part.id?"step":undefined} aria-label={`Question ${i+1}: ${part.title}, ${part.earned_points} of ${part.maximum_points} points, ${full(part)?"completed":"not completed"}`} title={`${part.title} · ${part.earned_points} / ${part.maximum_points} points`} onClick={()=>void onNavigate(part.id)}><span>{i+1}</span>{full(part)&&<Check size={12}/>}</button>)}</div>
 <div className="pset-step-controls"><button aria-label="Previous question" disabled={index<=0||busy} onClick={()=>void onNavigate(parts[index-1].id)}><ArrowLeft size={17}/>Back</button><button className="next-question" aria-label="Next question" disabled={index<0||index>=parts.length-1||busy} onClick={()=>void onNavigate(parts[index+1].id)}>Next<ArrowRight size={17}/></button></div></div></nav>;
}
