import {ArrowLeft,ArrowRight,CheckCircle2,CircleDashed,Clock3,ChartNoAxesColumn} from "lucide-react";

type Question={id:number;title:string;earned_points:string;maximum_points:string;status:string};
const points=(value:number|string)=>Number(value).toLocaleString(undefined,{maximumFractionDigits:3});
export default function QuizNavigator({questions,active,busy,earned,maximum,onNavigate}:{questions:Question[];active:number|null;busy:boolean;earned:number;maximum:number;onNavigate:(id:number)=>Promise<void>}) {
  const index=questions.findIndex(question=>question.id===active);
  const full=(question:Question)=>Number(question.maximum_points)>0 && Number(question.earned_points)>=Number(question.maximum_points);
  const completed=questions.filter(full).length;
  return <nav className="quiz-question-nav" aria-label="Quiz questions">
    <section className={`quiz-live-score ${maximum>0 && earned>=maximum?"all-earned":""}`} aria-label="Live quiz score">
      <div className="quiz-score-label"><ChartNoAxesColumn size={17}/><span>Quiz score</span><span className="quiz-live-indicator">Live</span></div>
      <div className="quiz-score-number" role="status" aria-live="polite" aria-atomic="true"><strong>{points(earned)}</strong><span>/ {points(maximum)}</span></div>
      <progress aria-label="Quiz points earned" value={earned} max={maximum||1}/>
      <p><CheckCircle2 size={15}/>{completed} of {questions.length} questions at full credit</p>
    </section>
    <div className="quiz-question-panel">
      <div className="quiz-navigation-heading"><div><h2>Questions</h2><span>Question {Math.max(1,index+1)} of {questions.length}</span></div>
        <div className="quiz-step-controls"><button aria-label="Previous question" title="Previous question" disabled={index<=0 || busy} onClick={()=>void onNavigate(questions[index-1].id)}><ArrowLeft size={19}/></button><button aria-label="Next question" title="Next question" disabled={index<0 || index>=questions.length-1 || busy} onClick={()=>void onNavigate(questions[index+1].id)}><ArrowRight size={19}/></button></div>
      </div>
      <div className="quiz-question-buttons">{questions.map((question,n)=>{
        const complete=full(question),partial=!complete && Number(question.earned_points)>0;
        const state=complete?"Full credit":partial?"Partial credit":question.status==="new"?"Not started":"In progress";
        const Icon=complete?CheckCircle2:question.status==="new"?CircleDashed:Clock3;
        return <button key={question.id} className={`quiz-question-card ${question.id===active?"active":""} ${complete?"complete":partial?"partial":""}`}
          aria-label={`Question ${n+1}: ${question.title}, ${points(question.earned_points)} of ${points(question.maximum_points)} points, ${state}`}
          aria-current={question.id===active?"step":undefined} title={`${question.title} · ${state}`} disabled={busy} onClick={()=>void onNavigate(question.id)}>
          <span className="quiz-question-card-top"><strong>Q{n+1}</strong><Icon size={17}/></span>
          <span className="quiz-question-card-points">{points(question.earned_points)}<span> / {points(question.maximum_points)}</span></span>
          <span className="quiz-question-card-state">{state}</span>
        </button>;
      })}</div>
    </div>
  </nav>;
}
