type Client = {
  init:()=>Promise<void>;
  onExamSubmit:(callback:()=>void)=>void;
  examSubmit:()=>void;
};
export type CompletionSignal = "requested" | "unavailable";

// This is an extension notification, not an acknowledgement that recording stopped.
// Never create/replace a session or send identity, questions, code, or credentials.
export function createHonorlockBridge(loadClient:()=>Promise<Client>) {
  let pending:Promise<Client|null>|undefined;
  let submitted=false;
  function prepare() {
    if(!pending)pending=loadClient().then(async client=>{
      await client.init();
      client.onExamSubmit(()=>{});
      return client;
    }).catch(()=>null);
    return pending;
  }
  async function notifySubmitted():Promise<CompletionSignal> {
    if(submitted)return "requested";
    const client=await prepare();
    if(!client)return "unavailable";
    // Two concurrent completion handlers must never notify twice.
    if(submitted)return "requested";
    try {client.examSubmit();submitted=true;return "requested";}
    catch {return "unavailable";}
  }
  return {prepare,notifySubmitted};
}

export function newHonorlockBridge() {
  return createHonorlockBridge(async()=>{
    const {Honorlock}=await import("@honorlock/integration-sdk-js");
    return new Honorlock();
  });
}
