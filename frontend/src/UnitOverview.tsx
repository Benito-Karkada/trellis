import {useRef,useState} from "react";
import {ArrowUpRight,ArrowRight,ChevronDown,Check,ClipboardList,PackageOpen,X} from "lucide-react";
import {routeHref} from "./navigation";
type Part={id:number;title:string;status:string;earned_points:string;maximum_points:string;metadata?:{kind?:string;category?:string}};
type Lesson={id:number;title:string;metadata?:{kind?:string;unit_number?:number;earned_points?:string;maximum_points?:string;activity_count?:number;completed_count?:number};activities:Part[]};
const names:Record<string,string>={"1":"Computing foundations","2":"Procedural programming","3":"Control structures","4":"Data structures","5":"Objects & algorithms",final:"Final problem set",other:"More coursework"};
function unitOf(lesson:Lesson){return lesson.title.match(/(?:Chapter|Unit)\s+(\d+)/i)?.[1] || (/final/i.test(lesson.title)?"final":"other");}
function quizUnit(quiz:Lesson){const number=Number(quiz.title.match(/(\d+)\s*$/)?.[1]);return String(quiz.metadata?.unit_number || ({1:3,2:3,3:3,4:4,5:4,6:5} as Record<number,number>)[number] || "other");}
const points=(n:number)=>n.toLocaleString(undefined,{maximumFractionDigits:2});
const preferenceKey="trellis:unboxed-units:v1";
function initialOpened(){try{const saved:unknown=JSON.parse(localStorage.getItem(preferenceKey)||"[]");return new Set(Array.isArray(saved)?saved.filter((id):id is string=>typeof id==="string"):[]);}catch{return new Set<string>();}}

function CourseBox({label}:{label:string}){
 return <svg className="course-box-art" viewBox="0 0 300 210" fill="none" aria-hidden="true">
  <ellipse cx="150" cy="187" rx="112" ry="10" fill="#16130f" opacity=".08"/>
  <g className="box-carton"><path d="M42 83 148 47 258 83 258 163 150 198 42 163Z" fill="#e4cba7" stroke="#16130f" strokeWidth="2.5" strokeLinejoin="round"/>
  <path d="m42 83 108 36 108-36M150 119v79" stroke="#16130f" strokeWidth="2.5"/>
  <path d="m42 83 106-36 110 36-108 36Z" fill="#f2dfbd" stroke="#16130f" strokeWidth="2.5"/>
  <path d="m125 55 22-8 110 36-23 8Z" fill="#ffd23f" stroke="#16130f" strokeWidth="1.5"/>
  <path d="m234 91 23-8v34l-23 8Z" fill="#ffd23f" stroke="#16130f" strokeWidth="1.5"/>
  <path className="box-lid-fold" d="m42 83 108 36-1-39L42 44Z" fill="#ead3ac" stroke="#16130f" strokeWidth="2.5" strokeLinejoin="round"/>
  <path className="box-lid-mark" d="m42 83 108 36-1-39L42 44Z" fill="#f0ddbc" stroke="#16130f" strokeWidth="2.5" strokeLinejoin="round"/>
  <path d="m64 111 65 22v34l-65-22Z" fill="#fffefa" stroke="#16130f" strokeWidth="1.5"/>
  <path d="m72 124 36 12m-36-4 47 16m-47-8 28 10" stroke="#2d5be3" strokeWidth="3"/>
  <path d="m176 138 55-18v35l-55 18Z" fill="#2d5be3" stroke="#16130f" strokeWidth="1.5"/>
  <text x="185" y="153" fill="#fffefa" fontFamily="monospace" fontSize="12" fontWeight="700" transform="rotate(-18 185 153)">{label}</text></g>
 </svg>;
}

export default function UnitOverview({lessons,quizzes,onOpen}:{lessons:Lesson[];quizzes:Lesson[];onOpen:(lesson:number,part:number|null)=>void}){
 const [expanded,setExpanded]=useState<Set<number>>(new Set());
 const [opened,setOpened]=useState(initialOpened);
 const openButtons=useRef<Record<string,HTMLButtonElement|null>>({});
 const closeButtons=useRef<Record<string,HTMLButtonElement|null>>({});
 const keys=[...new Set([...lessons.map(unitOf),...quizzes.map(quizUnit)])];
 function toggle(key:string){
  const opening=!opened.has(key),next=new Set(opened);
  if(opening)next.add(key);else next.delete(key);
  setOpened(next);
  try{localStorage.setItem(preferenceKey,JSON.stringify([...next]));}catch{/* Presentation still works if storage is unavailable. */}
  requestAnimationFrame(()=>{(opening?closeButtons:openButtons).current[key]?.focus({preventScroll:true});});
 }
 function link(lesson:Lesson,part?:Part){const target=part||lesson.activities[0];return routeHref({page:"course",lessonId:lesson.id,active:target?.id||null,category:target?.metadata?.category||"content"});}
 function click(event:React.MouseEvent,lesson:Lesson,part?:Part){if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();onOpen(lesson.id,part?.id||lesson.activities[0]?.id||null);}
 return <section className="unit-overview" aria-label="Course units"><div className="unit-overview-heading"><div><span className="section-kicker">YOUR COURSE</span><h2>Course units</h2></div><span>{lessons.length} chapters · {quizzes.length} quizzes</span></div>
 <div className="unit-grid">{keys.map((key,i)=>{
  const chapters=lessons.filter(l=>unitOf(l)===key),assessments=quizzes.filter(q=>quizUnit(q)===key),unboxed=opened.has(key);
  const count=chapters.reduce((n,l)=>n+(l.metadata?.activity_count??l.activities.length),0),done=chapters.reduce((n,l)=>n+(l.metadata?.completed_count??l.activities.filter(a=>a.status==="completed").length),0);
  const label=key==="final"?"FINALE":key==="other"?"EXTRA":`UNIT ${key}`;
  return <article key={key} className={`unit-card ${unboxed?"unboxed":"sealed"}`} style={{"--unit-order":i} as React.CSSProperties}>
   <header className="unit-card-heading"><span className="unit-number">{key==="final"?<PackageOpen size={25}/>:key==="other"?"+":key.padStart(2,"0")}</span><div><span className="section-kicker">{label}</span><h3>{names[key]||`Unit ${key}`}</h3></div><span className="unit-fraction">{done}<span> / {count}</span></span>
    {unboxed&&<button ref={node=>{closeButtons.current[key]=node;}} className="close-unit" aria-label={`Close ${label.toLowerCase()}`} onClick={()=>toggle(key)}><X size={16}/></button>}
   </header>
   <progress aria-label={`${names[key]||key} progress`} value={done} max={count||1}/>
   <div className="unit-body">
    <div className="unit-box-cover" aria-hidden={unboxed} inert={unboxed}>
     <CourseBox label={label}/><div className="unit-package-details"><span>{chapters.length} chapter{chapters.length===1?"":"s"}</span><span>{assessments.length} quiz{assessments.length===1?"":"zes"}</span><span>{count} parts</span></div>
     <button ref={node=>{openButtons.current[key]=node;}} className="unbox-button" aria-expanded={unboxed} aria-controls={`unit-contents-${key}`} onClick={()=>toggle(key)}><PackageOpen size={19}/>Unbox {key==="final"?"final problem set":key==="other"?"coursework":`unit ${key}`}<ArrowRight size={18}/></button>
    </div>
    <div id={`unit-contents-${key}`} className="unit-contents" role="region" aria-label={`${label} chapters and quizzes`} aria-hidden={!unboxed} inert={!unboxed} tabIndex={unboxed?0:-1}>
     <div className="unit-chapters">{chapters.map(chapter=>{
      const open=expanded.has(chapter.id),total=chapter.metadata?.activity_count??chapter.activities.length,completed=chapter.metadata?.completed_count??chapter.activities.filter(a=>a.status==="completed").length;
      const earned=Number(chapter.metadata?.earned_points||0),maximum=Number(chapter.metadata?.maximum_points||0);
      return <section key={chapter.id} className={`unit-chapter ${open?"expanded":""}`}><div className="chapter-heading"><button className="chapter-disclosure" aria-label={`${open?"Collapse":"Expand"} ${chapter.title}`} aria-expanded={open} aria-controls={`chapter-parts-${chapter.id}`} onClick={()=>setExpanded(old=>{const next=new Set(old);if(next.has(chapter.id))next.delete(chapter.id);else next.add(chapter.id);return next;})}><ChevronDown size={17}/></button>
       <a href={link(chapter)} onClick={e=>click(e,chapter)}><strong>{chapter.title.replace(/^Chapter\s*/i,"").replace(/(\d+\.\d+)\s*[-–—]\s*/,"$1 · ")}</strong><small>{total} parts{maximum>0?` · ${points(earned)} / ${points(maximum)} points`:""}</small></a>{completed===total&&total>0?<Check className="chapter-complete" size={18}/>:<a className="chapter-open" aria-label={`Open ${chapter.title}`} href={link(chapter)} onClick={e=>click(e,chapter)}><ArrowUpRight size={18}/></a>}</div>
       {open&&<div id={`chapter-parts-${chapter.id}`} className="chapter-parts">{chapter.activities.filter(a=>a.metadata?.category!=="problem_set").map(part=><a key={part.id} href={link(chapter,part)} onClick={e=>click(e,chapter,part)}><span className={`part-dot ${part.status==="completed"?"done":""}`}>{part.status==="completed"&&<Check size={10}/>}</span>{part.title}</a>)}{chapter.activities.some(a=>a.metadata?.category==="problem_set")&&<a className="chapter-pset-link" href={link(chapter,chapter.activities.find(a=>a.metadata?.category==="problem_set"))} onClick={e=>click(e,chapter,chapter.activities.find(a=>a.metadata?.category==="problem_set"))}><PackageOpen size={15}/>Problem set<ArrowUpRight size={15}/></a>}</div>}
      </section>;
     })}</div>
     {!!assessments.length&&<div className="unit-quizzes"><span className="section-kicker">PROGRAMMING QUIZZES</span>{assessments.map(quiz=><a key={quiz.id} href={link(quiz)} onClick={e=>click(e,quiz)}><span className="quiz-unit-icon"><ClipboardList size={18}/></span><span><strong>{quiz.title}</strong><small>{quiz.metadata?.activity_count??quiz.activities.length} questions · {points(Number(quiz.metadata?.earned_points||0))} / {points(Number(quiz.metadata?.maximum_points||0))} points</small></span><ArrowUpRight size={18}/></a>)}</div>}
    </div>
   </div>
  </article>;
 })}</div></section>;
}
