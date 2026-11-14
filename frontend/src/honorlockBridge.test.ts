import test from "node:test";
import assert from "node:assert/strict";
import {createHonorlockBridge} from "./honorlockBridge.ts";

test("initialization is shared and never sends completion until requested",async()=>{
  const calls:string[]=[];
  const bridge=createHonorlockBridge(async()=>({init:async()=>{calls.push("init");},onExamSubmit:()=>{calls.push("callback");},examSubmit:()=>{calls.push("submit");}}));
  await Promise.all([bridge.prepare(),bridge.prepare()]);
  assert.deepEqual(calls,["init","callback"]);
  assert.equal(await bridge.notifySubmitted(),"requested");
  assert.deepEqual(calls,["init","callback","submit"]);
});
test("missing or incompatible extension returns unavailable without false success",async()=>{
  let sent=false;
  const bridge=createHonorlockBridge(async()=>({init:async()=>{throw Error("extension timeout");},onExamSubmit:()=>{},examSubmit:()=>{sent=true;}}));
  assert.equal(await bridge.notifySubmitted(),"unavailable");assert.equal(sent,false);
});
test("SDK failure does not claim completion or prevent a saved quiz from closing",async()=>{
  const bridge=createHonorlockBridge(async()=>({init:async()=>{},onExamSubmit:()=>{},examSubmit:()=>{throw Error("disconnected");}}));
  assert.equal(await bridge.notifySubmitted(),"unavailable");
});
test("concurrent finalization sends only one completion signal",async()=>{
  let sent=0;
  const bridge=createHonorlockBridge(async()=>({init:async()=>{},onExamSubmit:()=>{},examSubmit:()=>{sent++;}}));
  assert.deepEqual(await Promise.all([bridge.notifySubmitted(),bridge.notifySubmitted()]),["requested","requested"]);assert.equal(sent,1);
});
