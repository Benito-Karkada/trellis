export function csrfToken(){return document.cookie.split("; ").find(x=>x.startsWith("csrftoken="))?.split("=")[1]||""}

export async function api(path:string,body?:unknown){
 const response=await fetch("/api/"+path,{credentials:"same-origin",...(body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-CSRFToken":csrfToken()},body:JSON.stringify(body)})});
 const data=await response.json().catch(()=>({}));
 if(!response.ok)throw Error(data.error||`Request failed (${response.status}).`);
 return data;
}

export async function upload(path:string,body:FormData){
 const response=await fetch("/api/"+path,{method:"POST",credentials:"same-origin",headers:{"X-CSRFToken":csrfToken()},body});
 const data=await response.json().catch(()=>({}));
 if(!response.ok)throw Error(data.error||`Request failed (${response.status}).`);
 return data;
}
