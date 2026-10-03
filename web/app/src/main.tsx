import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/app.css";
import { apply } from "./lib/prefs";
import { App } from "./App";

apply();
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
