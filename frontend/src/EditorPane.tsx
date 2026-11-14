import {useEffect,useRef} from "react";
// Register language services before the first editor creates its service container.
import "monaco-editor/internal/common/workers.js";
import Editor,{loader} from "@monaco-editor/react";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/languages/definitions/python/register.js";
import "monaco-editor/languages/definitions/shell/register.js";
import "monaco-editor/languages/features/json/register.js";
import JSONWorker from "monaco-editor/languages/features/json/json.worker.js?worker";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
self.MonacoEnvironment={getWorker:(_id,label)=>label==="json"?new JSONWorker():new EditorWorker()};
loader.config({monaco});
export default function EditorPane({value,onChange,path,disabled,theme,ariaLabel,height="450px",activeLine}:{value:string;onChange:(value:string)=>void;path:string;disabled:boolean;theme:"light"|"dark";ariaLabel?:string;height?:string;activeLine?:number}){
 const editorRef=useRef<monaco.editor.IStandaloneCodeEditor|null>(null);
 const decorations=useRef<monaco.editor.IEditorDecorationsCollection|null>(null);
 function highlight(editor:monaco.editor.IStandaloneCodeEditor){
   decorations.current?.clear();
   if(activeLine){decorations.current=editor.createDecorationsCollection([{range:new monaco.Range(activeLine,1,activeLine,1),options:{isWholeLine:true,className:"viz-active-line",linesDecorationsClassName:"viz-active-gutter"}}]);editor.revealLineInCenterIfOutsideViewport(activeLine);}
 }
 useEffect(()=>{if(editorRef.current)highlight(editorRef.current);},[activeLine,path,value]);
 const json=path.endsWith(".json");
 return <Editor height={height} path={path} language={json?"json":path.endsWith(".py")?"python":path.endsWith(".sh")?"shell":"plaintext"}
 beforeMount={api=>{api.editor.defineTheme("trellis-light",{base:"vs",inherit:true,rules:[],colors:{"editor.background":"#ffffff","editor.foreground":"#162b2a","editorLineNumber.foreground":"#82918a","editorLineNumber.activeForeground":"#425852","editor.lineHighlightBackground":"#e8eee880","editorCursor.foreground":"#425852","editor.selectionBackground":"#dce8df"}});api.editor.defineTheme("trellis-dark",{base:"vs-dark",inherit:true,rules:[],colors:{"editor.background":"#121c33","editor.foreground":"#edf1ff","editorLineNumber.foreground":"#8392b8","editorLineNumber.activeForeground":"#b2a4ff","editor.lineHighlightBackground":"#263354","editorCursor.foreground":"#b2a4ff","editor.selectionBackground":"#4d407e"}});}}
 theme={theme==="dark"?"trellis-dark":"trellis-light"} value={value} onChange={(value,event)=>{if(!event.isFlush)onChange(value||"");}} onMount={editor=>{editorRef.current=editor;highlight(editor);editor.onKeyDown(event=>{if(event.keyCode===monaco.KeyCode.Tab && !event.ctrlKey && !event.altKey && !event.metaKey){event.preventDefault();event.stopPropagation();editor.trigger('keyboard',event.shiftKey?'outdent':'tab',{});}});}}
 options={{ariaLabel:ariaLabel||'Code editor',lineNumbers:'on',colorDecorators:false,fontSize:14,minimap:{enabled:false},wordWrap:"on",padding:{top:18},scrollBeyondLastLine:false,automaticLayout:true,readOnly:disabled,tabSize:json?2:4,insertSpaces:true,detectIndentation:false,formatOnPaste:json,formatOnType:json}}/>;
}
