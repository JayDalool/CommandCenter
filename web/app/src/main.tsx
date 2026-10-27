import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/control.css";
import "./hq/tokens.css"; // HQ design tokens: inert unless <html data-ui="hq">
import { apply } from "./lib/prefs";
import { installStaleBuildHandler } from "./lib/stale";
import { App } from "./App";

apply();
installStaleBuildHandler();
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
