const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("adalaDesktop", {
  version: "1.0.0",
});
