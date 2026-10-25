import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/hq.css";
import "./styles/theme-light.css";
import "./lib/theme";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
