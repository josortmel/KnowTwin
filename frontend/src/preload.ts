import { contextBridge, ipcRenderer } from "electron";
import type { KnowtwinBridge, KnowtwinWsEvent } from "./types/electron";

// The renderer talks to the API only through this bridge. The MAIN process owns
// the API key and attaches the Bearer header / WS ?key inside fetch/ws — the key
// is never sent to the renderer. There is deliberately NO getToken/getApiKey.
let wsSeq = 0;

const bridge: KnowtwinBridge = {
  fetch: (path, opts) => ipcRenderer.invoke("knowtwin:fetch", { path, opts }),

  setApiKey: (key) => ipcRenderer.invoke("knowtwin:setApiKey", key),
  // Sync so an auth gate can read it without awaiting; returns a pure boolean.
  hasApiKey: () => ipcRenderer.sendSync("knowtwin:hasApiKey") as boolean,
  clearApiKey: () => ipcRenderer.invoke("knowtwin:clearApiKey"),
  saveFile: (content, filename) => ipcRenderer.invoke("knowtwin:saveFile", { content, filename }),
  uploadDocument: (args) => ipcRenderer.invoke("knowtwin:uploadDocument", args),
  uploadVoice: (args) => ipcRenderer.invoke("knowtwin:uploadVoice", args),
  getConfig: () => ipcRenderer.invoke("knowtwin:getConfig"),
  setConfig: (cfg) => ipcRenderer.invoke("knowtwin:setConfig", cfg),

  wsConnect: ({ projectId, sessionId }, onEvent) => {
    const id = `ws_${Date.now()}_${wsSeq++}`;
    const channel = `knowtwin:ws:event:${id}`;
    const listener = (_e: unknown, payload: KnowtwinWsEvent) => onEvent(payload);
    ipcRenderer.on(channel, listener);
    void ipcRenderer.invoke("knowtwin:ws:connect", { id, projectId, sessionId });
    return {
      send: (data: string) => {
        void ipcRenderer.invoke("knowtwin:ws:send", { id, data });
      },
      close: () => {
        ipcRenderer.removeListener(channel, listener);
        void ipcRenderer.invoke("knowtwin:ws:close", { id });
      },
    };
  },
};

contextBridge.exposeInMainWorld("knowtwin", bridge);
